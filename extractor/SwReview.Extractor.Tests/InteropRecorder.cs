using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.Remoting;
using System.Runtime.Remoting.Messaging;
using System.Runtime.Remoting.Proxies;

namespace SwReview.Extractor.Tests;

/// <summary>
/// A stand-in for a SOLIDWORKS interop object that records every member called on it, under the
/// name the interop declares it by (a property read is <c>get_X</c>, a write <c>set_X</c>), with
/// its arguments, and answers what the test set for that member - or the return type's default. A
/// transparent proxy, so a test can name the interop type without writing out its members; no COM
/// object exists and SOLIDWORKS is never started.
///
/// One stand-in can be more than one interface, as a real COM object is: a part's document is an
/// <c>IModelDoc2</c> and an <c>IPartDoc</c> at once, and the adapter reaches the second by a cast.
/// Every interface named at construction is one the stand-in can be cast to (and each interface
/// they derive from); any other cast fails, as it would on a real object that is not one.
///
/// Written once and shared: lane A's tests (feature 004's build order) use it here, and
/// <c>SwReview.AddIn.Tests</c> compiles this same file (a link in its project file) for the seat
/// adapter's tests, so the two suites cannot grow two recorders that drift apart.
/// </summary>
internal sealed class InteropRecorder<TInterface> : RealProxy, IRemotingTypeInfo
    where TInterface : class
{
    private readonly Type[] _interfaces;
    private readonly Dictionary<string, object?> _answers = new Dictionary<string, object?>(StringComparer.Ordinal);
    private readonly Dictionary<string, Func<object?[], object?>> _handlers =
        new Dictionary<string, Func<object?[], object?>>(StringComparer.Ordinal);

    private readonly Dictionary<string, Exception> _failures = new Dictionary<string, Exception>(StringComparer.Ordinal);

    /// <param name="also">The other interfaces this stand-in is, beside <typeparamref name="TInterface"/>.</param>
    public InteropRecorder(params Type[] also)
        : base(typeof(TInterface))
    {
        _interfaces = new[] { typeof(TInterface) }.Concat(also ?? Array.Empty<Type>()).ToArray();
        foreach (Type type in _interfaces)
        {
            if (!type.IsInterface)
            {
                throw new ArgumentException($"{type.Name} is not an interface; a stand-in is only ever interfaces.", nameof(also));
            }
        }
    }

    public TInterface Instance => (TInterface)GetTransparentProxy();

    /// <summary>Every member called, in order, with the arguments it was handed.</summary>
    public List<(string Member, object?[] Arguments)> Calls { get; } = new List<(string, object?[])>();

    /// <summary>The members called, in order and with repeats.</summary>
    public IReadOnlyList<string> Members => Calls.Select(call => call.Member).ToList();

    string IRemotingTypeInfo.TypeName { get; set; } = typeof(TInterface).FullName!;

    /// <summary>The stand-in as another of the interfaces it was built as.</summary>
    public T As<T>()
        where T : class => (T)GetTransparentProxy();

    public InteropRecorder<TInterface> Answer(string member, object? answer)
    {
        _answers[member] = answer;
        return this;
    }

    /// <summary>
    /// Answers <paramref name="member"/> from <paramref name="handler"/>, which is handed the call's
    /// arguments and may set its by-ref (out) ones in place.
    /// </summary>
    public InteropRecorder<TInterface> Handle(string member, Func<object?[], object?> handler)
    {
        _handlers[member] = handler ?? throw new ArgumentNullException(nameof(handler));
        return this;
    }

    public InteropRecorder<TInterface> Fail(string member, Exception failure)
    {
        _failures[member] = failure;
        return this;
    }

    bool IRemotingTypeInfo.CanCastTo(Type fromType, object o) =>
        _interfaces.Any(type => fromType.IsAssignableFrom(type));

    public override IMessage Invoke(IMessage message)
    {
        var call = (IMethodCallMessage)message;
        var method = (MethodInfo)call.MethodBase;
        object?[] arguments = call.Args ?? new object?[0];

        // Object's own members reach a transparent proxy too. They are answered here, as the
        // object's identity, and are not interop calls, so they are not recorded: a stand-in
        // used as a dictionary key or compared by an assertion is equal to itself alone.
        if (method.DeclaringType == typeof(object))
        {
            return new ReturnMessage(ObjectMember(method.Name, arguments), null, 0, call.LogicalCallContext, call);
        }

        Calls.Add((call.MethodName, (object?[])arguments.Clone()));

        if (_failures.TryGetValue(call.MethodName, out Exception? failure))
        {
            return new ReturnMessage(failure, call);
        }

        ParameterInfo[] parameters = method.GetParameters();
        for (int index = 0; index < parameters.Length; index++)
        {
            Type type = parameters[index].ParameterType;
            if (type.IsByRef && arguments[index] == null && type.GetElementType()!.IsValueType)
            {
                arguments[index] = Activator.CreateInstance(type.GetElementType()!);
            }
        }

        object? answer;
        if (_handlers.TryGetValue(call.MethodName, out Func<object?[], object?>? handler))
        {
            answer = handler(arguments);
        }
        else if (_answers.TryGetValue(call.MethodName, out object? set))
        {
            answer = set;
        }
        else
        {
            Type returns = method.ReturnType;
            answer = returns.IsValueType && returns != typeof(void) ? Activator.CreateInstance(returns) : null;
        }

        return new ReturnMessage(answer, arguments, arguments.Length, call.LogicalCallContext, call);
    }

    private object ObjectMember(string name, object?[] arguments)
    {
        switch (name)
        {
            case nameof(Equals):
                return ReferenceEquals(arguments[0], GetTransparentProxy());
            case nameof(GetHashCode):
                return RuntimeHelpers.GetHashCode(this);
            case nameof(ToString):
                return "stand-in " + typeof(TInterface).Name;
            default:
                throw new NotSupportedException($"object.{name} is not answered by a stand-in.");
        }
    }
}
