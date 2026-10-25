using System;

namespace SwReview.AddIn;

/// <summary>
/// Follows the active document immediately except while the bridge's actual copy open is on
/// the stack (004 T275). Native open can pump queued messages, so posting alone is not a fence.
/// All methods and callbacks run on the application thread; no COM document is captured in a queue.
/// </summary>
internal sealed class ConfigurationFollowCoordinator : IDisposable
{
    private readonly Action<Action> _post;
    private readonly Func<object?> _resolve;
    private readonly Action<object?> _follow;
    private readonly Action<Exception> _report;
    private int _opening;
    private bool _pending;
    private bool _queued;
    private bool _following;
    private bool _disposed;

    public ConfigurationFollowCoordinator(
        Action<Action> post, Func<object?> resolve, Action<object?> follow, Action<Exception> report)
    {
        _post = post ?? throw new ArgumentNullException(nameof(post));
        _resolve = resolve ?? throw new ArgumentNullException(nameof(resolve));
        _follow = follow ?? throw new ArgumentNullException(nameof(follow));
        _report = report ?? throw new ArgumentNullException(nameof(report));
    }

    public void Request()
    {
        if (_disposed) return;
        _pending = true;
        FollowNow();
    }

    public IDisposable? BeginRemodelOpen()
    {
        if (_disposed) return null;
        // A complete open can reenter ActiveDoc and return before its getter does.
        if (_following) _pending = true;
        _opening++;
        return new OpenScope(this);
    }

    public void Dispose()
    {
        _disposed = true;
        _pending = false;
        _queued = false;
        _opening = 0;
    }

    private void FollowNow()
    {
        if (_disposed || _opening != 0 || _following || !_pending) return;
        _following = true;
        _pending = false;
        try
        {
            object? activeDocument = _resolve();
            // Even ActiveDoc can pump messages: unloading or a replacement invalidates this
            // coordinator, an open raises the fence, and a newer request invalidates the result.
            if (_disposed) return;
            if (_opening != 0 || _pending)
            {
                _pending = true;
                return;
            }

            _follow(activeDocument);
        }
        catch (Exception failure)
        {
            Report(failure);
        }
        finally
        {
            _following = false;
            PostIfNeeded();
        }
    }

    private void EndOpen()
    {
        if (_disposed) return;
        _opening--;
        PostIfNeeded();
    }

    private void PostIfNeeded()
    {
        if (_disposed || _opening != 0 || _following || !_pending || _queued) return;
        _queued = true;
        try
        {
            _post(Flush);
        }
        catch (Exception failure)
        {
            _queued = false;
            Report(failure);
        }
    }

    private void Flush()
    {
        _queued = false;
        // When pumped inside another open, pending work stays pending without reposting.
        // Its final exit, not this nested pump, queues the next attempt.
        FollowNow();
    }

    private void Report(Exception failure)
    {
        try
        {
            _report(failure);
        }
        catch (Exception)
        {
            // Logging must not escape a document event or the posted application-thread callback.
        }
    }

    private sealed class OpenScope : IDisposable
    {
        private ConfigurationFollowCoordinator? _owner;

        public OpenScope(ConfigurationFollowCoordinator owner) => _owner = owner;

        public void Dispose()
        {
            ConfigurationFollowCoordinator? owner = _owner;
            _owner = null;
            owner?.EndOpen();
        }
    }
}
