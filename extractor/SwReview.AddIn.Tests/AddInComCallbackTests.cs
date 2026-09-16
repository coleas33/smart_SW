using System;
using System.IO;
using System.Runtime.InteropServices;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// The add-in has to be usable as a late-bound callback target, because that is the only way
/// SOLIDWORKS ever calls back into it.
///
/// <c>ISldWorks.SetAddinCallbackInfo2(ModuleHandle, AddinCallbacks, Cookie)</c> marshals its
/// <c>AddinCallbacks</c> argument as <c>IDispatch</c> - Task Pane buttons and command items
/// name their handlers as strings, and SOLIDWORKS invokes them by name. A class declared
/// <see cref="ClassInterfaceType.None"/> generates no class interface, so its COM-callable
/// wrapper exposes <c>IUnknown</c> and the explicitly implemented <c>ISwAddin</c> and nothing
/// else; marshalling the instance for that argument then throws
/// <c>InvalidCastException: Specified cast is not valid</c> before any add-in code runs. The
/// add-in appears in Tools &gt; Add-ins, can be ticked, never loads, and leaves no log,
/// because the failure happens ahead of everything that logs (docs/addin-load-fix.md).
///
/// These cases reproduce that marshalling step in isolation, with no SOLIDWORKS involved.
///
/// Constructing the add-in runs its type initializer, which writes a load checkpoint. The
/// checkpoint is pointed at a temp folder for the life of each case: <c>addin.log</c> is the
/// file docs/addin-load-fix.md tells an engineer to read when the check box reverts, and a
/// line written by <c>dotnet test</c> is indistinguishable there from a real SOLIDWORKS
/// activation - which is the diagnostic confusion this change exists to remove.
/// </summary>
public sealed class AddInComCallbackTests : IDisposable
{
    private readonly string _logFolder;

    private readonly Func<string> _realLogFolder;

    public AddInComCallbackTests()
    {
        _logFolder = Path.Combine(
            Path.GetTempPath(), "SwReview.AddInComCallback.Tests", Guid.NewGuid().ToString("N"));
        _realLogFolder = AddInLog.Folder;
        AddInLog.Folder = () => _logFolder;
    }

    public void Dispose()
    {
        AddInLog.Folder = _realLogFolder;

        try
        {
            if (Directory.Exists(_logFolder))
            {
                Directory.Delete(_logFolder, recursive: true);
            }
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }

    /// <summary>
    /// The regression. This is exactly what the interop marshaller does to the
    /// <c>AddinCallbacks</c> argument of <c>SetAddinCallbackInfo2</c>.
    /// </summary>
    [Fact]
    public void TheAddInCanBeMarshalledAsAnIDispatchCallbackTarget()
    {
        var addIn = new SwReviewAddIn();

        IntPtr dispatch = IntPtr.Zero;
        try
        {
            dispatch = Marshal.GetIDispatchForObject(addIn);

            Assert.NotEqual(IntPtr.Zero, dispatch);
        }
        finally
        {
            if (dispatch != IntPtr.Zero)
            {
                Marshal.Release(dispatch);
            }
        }
    }

    /// <summary>
    /// The requirement stated as the attribute, so the reason survives even if the
    /// marshalling case above is ever weakened. <c>AutoDual</c> would also supply
    /// <c>IDispatch</c>; it is not used, because it additionally bakes a v-table class
    /// interface this add-in has no need to version.
    /// </summary>
    [Fact]
    public void TheAddInDoesNotSuppressItsClassInterface()
    {
        var attribute = (ClassInterfaceAttribute?)Attribute.GetCustomAttribute(
            typeof(SwReviewAddIn), typeof(ClassInterfaceAttribute));

        Assert.NotNull(attribute);
        Assert.Equal(ClassInterfaceType.AutoDispatch, attribute!.Value);
    }

    /// <summary>The precondition for either of the above to matter.</summary>
    [Fact]
    public void TheAddInIsComVisible()
    {
        var attribute = (ComVisibleAttribute?)Attribute.GetCustomAttribute(
            typeof(SwReviewAddIn), typeof(ComVisibleAttribute));

        Assert.NotNull(attribute);
        Assert.True(attribute!.Value);
    }
}
