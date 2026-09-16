using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;

namespace SwReview.AddIn;

/// <summary>
/// What a <c>bindingRedirect</c> would do, for a host that has no config to put one in.
///
/// The add-in's dependencies disagree about which <c>System.Runtime.CompilerServices.Unsafe</c>
/// they want - <c>System.Memory</c> 4.0.1.2 and <c>System.Threading.Tasks.Extensions</c> 4.2.0.1
/// reference 4.0.4.1, <c>System.Text.Json</c> 8.0.0.5 and <c>System.Text.Encodings.Web</c>
/// 8.0.0.0 reference 6.0.0.0 - and only one file of a given name can sit beside the add-in.
/// On .NET Framework that disagreement is reconciled by a <c>bindingRedirect</c> in the
/// <b>host's</b> <c>.exe.config</c>. <c>SLDWORKS.exe</c> ships no config, so the 4.0.4.1
/// request fails outright and takes <c>UserSettings.Load</c> - the add-in's first use of
/// <c>System.Text.Json</c>, on the <c>ConnectToSW</c> path - down with it.
///
/// So this answers a failed bind with the file of the same <b>simple name</b> beside the
/// add-in, ignoring the requested version. The CLR accepts an assembly returned from
/// <see cref="AppDomain.AssemblyResolve"/> whose version does not match the request; ordinary
/// probing, which is what failed a moment earlier, would refuse it.
///
/// Chosen over the alternatives because it travels with the add-in: authoring
/// <c>SLDWORKS.exe.config</c> would modify a vendor installation, need admin on every
/// workstation, affect SOLIDWORKS' own managed code and every other add-in, and be erased by
/// service packs; GAC-installing the shims would be machine-wide state that nothing in the
/// repository records as required; and shipping one matching <c>Unsafe</c> is impossible while
/// two consumers want different versions. See docs/addin-load-fix.md.
///
/// This event fires for <b>every</b> failed bind in the SOLIDWORKS process, other add-ins'
/// included, which is why <see cref="FileFor"/> answers only the names in
/// <see cref="Redirected"/> - the add-in's own NuGet shim graph - that also exist as a file
/// beside this add-in, and declines <c>.resources</c> requests. Every substitution it does
/// serve is written to <c>addin.log</c>, so a redirect that reached somebody else is on the
/// record rather than silent.
/// </summary>
public static class AssemblyRedirect
{
    private static readonly object Gate = new object();

    /// <summary>
    /// The only simple names this resolver will answer: the managed assemblies the add-in's
    /// own package graph puts beside it, which are the ones whose versions disagree and so the
    /// only ones a bind can fail on for want of a redirect.
    ///
    /// A named set rather than "any file beside the add-in", because the output folder also
    /// holds assemblies that <b>other</b> add-ins in the SOLIDWORKS process ship their own
    /// copies of - the seat's <c>SolidWorks.Interop.*</c>, staged there by
    /// register-addin.ps1, and WebView2 - and answering one of those with this add-in's copy
    /// would take over another add-in's binding. They are not here: this add-in pins WebView2
    /// and ships the matching file, so its own WebView2 binds succeed by ordinary probing and
    /// never reach this handler at all, and the interops are the seat's.
    ///
    /// A dependency added later that cannot bind in a host with no config has to be added
    /// here by name. That is the point: the blast radius is one list.
    /// </summary>
    private static readonly HashSet<string> Redirected =
        new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "Microsoft.Bcl.AsyncInterfaces",
            "System.Buffers",
            "System.Memory",
            "System.Numerics.Vectors",
            "System.Runtime.CompilerServices.Unsafe",
            "System.Text.Encodings.Web",
            "System.Text.Json",
            "System.Threading.Tasks.Extensions",
            "System.ValueTuple",
        };

    /// <summary>
    /// The directory the add-in was loaded from, and the only directory this resolver will
    /// serve a file out of.
    ///
    /// Read once here rather than per bind, because <see cref="Resolve"/> must not throw and
    /// this is the one expression on its path that can: <c>Assembly.CodeBase</c> throws
    /// <c>NotSupportedException</c> for a dynamic assembly and is empty for one loaded from a
    /// byte array, which <c>new Uri</c> rejects. A directory that cannot be named comes back
    /// empty, which <see cref="FileFor"/> declines like any other.
    /// </summary>
    internal static readonly string AddInDirectory = DirectoryOfThisAssembly();

    private static bool _installed;

    /// <summary>
    /// Installs the handler on the current AppDomain, once. Called from the
    /// <see cref="SwReviewAddIn"/> static constructor, which runs on COM activation - ahead of
    /// <c>ConnectToSW</c> and so ahead of the first bind that would fail. Returns true only
    /// for the call that subscribed.
    /// </summary>
    public static bool Install()
    {
        lock (Gate)
        {
            if (_installed)
            {
                return false;
            }

            AppDomain.CurrentDomain.AssemblyResolve += Resolve;
            _installed = true;
            return true;
        }
    }

    /// <summary>True once the handler is subscribed on this AppDomain.</summary>
    internal static bool Installed
    {
        get
        {
            lock (Gate)
            {
                return _installed;
            }
        }
    }

    /// <summary>
    /// The file this resolver would answer <paramref name="displayName"/> with, or null to
    /// decline. Pure: it reads <paramref name="directory"/> and nothing else, loads nothing,
    /// and never throws - an exception out of an <see cref="AppDomain.AssemblyResolve"/>
    /// handler surfaces as the binding failure of whichever component happened to be loading.
    /// </summary>
    public static string? FileFor(string displayName, string directory)
    {
        string? simpleName = SimpleNameOf(displayName);
        if (simpleName == null)
        {
            return null;
        }

        // The CLR asks for `<name>.resources` during localized lookups and expects to be told
        // no; answering with a code assembly would be wrong even where a file of that name
        // happens to exist.
        if (simpleName.EndsWith(".resources", StringComparison.OrdinalIgnoreCase))
        {
            return null;
        }

        // Somebody else's assembly, or one of ours that has no version disagreement to
        // reconcile. Either way its failed bind is not this add-in's to answer.
        if (!Redirected.Contains(simpleName))
        {
            return null;
        }

        try
        {
            string candidate = Path.Combine(directory, simpleName + ".dll");
            return File.Exists(candidate) ? candidate : null;
        }
        catch (ArgumentException)
        {
            // An invalid character in the name or the directory. Not ours to serve.
            return null;
        }
        catch (IOException)
        {
            return null;
        }
        catch (UnauthorizedAccessException)
        {
            return null;
        }
    }

    private static Assembly? Resolve(object sender, ResolveEventArgs args)
    {
        string requested = args.Name ?? string.Empty;

        string? file = FileFor(requested, AddInDirectory);
        if (file == null)
        {
            return null;
        }

        try
        {
            Assembly loaded = Assembly.LoadFrom(file);

            // This handler sees the whole process's failed binds, so a substitution may have
            // been served to something that is not this add-in. One line each, in the same
            // addin.log as the load checkpoints: it is a small number of binds per session,
            // and a cross-add-in interaction that left no record would be undiagnosable.
            AddInLog.Write(string.Format("AssemblyRedirect served '{0}' from {1}.", requested, file));

            return loaded;
        }
        catch (Exception)
        {
            // Declining leaves the caller with its own binding failure, which is the truthful
            // outcome and is what would have happened without this handler.
            return null;
        }
    }

    /// <summary>
    /// The folder this assembly was loaded from, or the empty string when it cannot be named.
    /// Guarded for the reason given on <see cref="AddInDirectory"/>: nothing on the
    /// <see cref="Resolve"/> path may throw, and this is the only expression there that could.
    /// </summary>
    private static string DirectoryOfThisAssembly()
    {
        try
        {
            return Path.GetDirectoryName(new Uri(typeof(AssemblyRedirect).Assembly.CodeBase).LocalPath)
                ?? string.Empty;
        }
        catch (Exception)
        {
            return string.Empty;
        }
    }

    /// <summary>
    /// The simple name out of an assembly display name, or null when there is not one.
    /// <c>AssemblyName</c> is the parser the CLR itself uses, so the two agree on the odd
    /// shapes - escaped characters, missing components - that hand-splitting on the first
    /// comma would get wrong.
    /// </summary>
    private static string? SimpleNameOf(string displayName)
    {
        if (string.IsNullOrWhiteSpace(displayName))
        {
            return null;
        }

        try
        {
            string name = new AssemblyName(displayName).Name;
            return string.IsNullOrEmpty(name) ? null : name;
        }
        catch (ArgumentException)
        {
            return null;
        }
        catch (FileLoadException)
        {
            // AssemblyName throws this for a display name it cannot parse.
            return null;
        }
    }
}
