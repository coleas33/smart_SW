using System;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// The add-in's dependencies disagree about which
/// <c>System.Runtime.CompilerServices.Unsafe</c> they want - <c>System.Memory</c> and
/// <c>System.Threading.Tasks.Extensions</c> ask for 4.0.4.1, <c>System.Text.Json</c> for
/// 6.0.0.0 - and only one file of that name can sit beside the add-in. On .NET Framework that
/// is normally reconciled by a <c>bindingRedirect</c> in the <b>host's</b> <c>.exe.config</c>;
/// <c>SLDWORKS.exe</c> ships no config, so the first use of <c>System.Text.Json</c> - which is
/// <c>UserSettings.Load</c>, on the <c>ConnectToSW</c> path - fails to bind
/// (docs/addin-load-fix.md, cause 2). <see cref="SwReview.AddIn.AssemblyRedirect"/> answers
/// that failed bind with the file of the same simple name beside the add-in.
///
/// Most of these cases assert the resolver as a <b>pure function</b> of a display name and a
/// directory rather than by loading anything, because this test host does have the redirects
/// the real host lacks (<c>AutoGenerateBindingRedirects</c> in the test project) and would
/// mask every one of them. A test that exercises the dependency graph inside the test host is
/// structurally incapable of catching this bug.
///
/// The last four go past that predicate on purpose, because a correct predicate wired to
/// nothing is still the load failure: the directory the handler actually serves out of, the
/// once-only install, the installed handler declining a real failed bind rather than throwing
/// out of it, and - in a child AppDomain, so that it cannot pass vacuously - the add-in's
/// static constructor being what installs it.
/// </summary>
public sealed class AssemblyRedirectTests
{
    private const string Unsafe = "System.Runtime.CompilerServices.Unsafe";

    private const string Token = "PublicKeyToken=b03f5f7f11d50a3a";

    /// <summary>
    /// The regression: the bind that fails inside SOLIDWORKS asks for 4.0.4.1, and the only
    /// file on disk is 6.0.0.0. The CLR accepts an assembly returned from
    /// <c>AssemblyResolve</c> whose version does not match the request; ordinary probing,
    /// which is what fails first, would refuse it.
    /// </summary>
    [Fact]
    public void AnOlderVersionRequestIsServedByTheFileBesideTheAddIn()
    {
        using (var temp = new TempFolder())
        {
            string file = temp.Write(Unsafe + ".dll");

            string? served = AssemblyRedirect.FileFor(
                $"{Unsafe}, Version=4.0.4.1, Culture=neutral, {Token}", temp.Path);

            Assert.Equal(file, served);
        }
    }

    /// <summary>
    /// The version is ignored, not compared: a request newer than the file on disk is served
    /// by the same file. Stated separately from the case above so "ignoring the requested
    /// version" cannot decay into "serving only downgrades".
    /// </summary>
    [Fact]
    public void ANewerVersionRequestIsServedByTheFileBesideTheAddIn()
    {
        using (var temp = new TempFolder())
        {
            string file = temp.Write(Unsafe + ".dll");

            string? served = AssemblyRedirect.FileFor(
                $"{Unsafe}, Version=9.9.9.9, Culture=neutral, {Token}", temp.Path);

            Assert.Equal(file, served);
        }
    }

    /// <summary>
    /// A by-name bind carries no version at all, and is served by the same file.
    /// </summary>
    [Fact]
    public void ARequestWithNoVersionIsServedByTheFileBesideTheAddIn()
    {
        using (var temp = new TempFolder())
        {
            string file = temp.Write(Unsafe + ".dll");

            string? served = AssemblyRedirect.FileFor(Unsafe, temp.Path);

            Assert.Equal(file, served);
        }
    }

    /// <summary>
    /// The handler is installed on the whole SOLIDWORKS AppDomain and fires for every failed
    /// bind in the process, including other add-ins'. A name with no file beside this add-in
    /// is somebody else's failure and must stay that way.
    /// </summary>
    [Fact]
    public void AnUnknownSimpleNameIsNotServed()
    {
        using (var temp = new TempFolder())
        {
            temp.Write(Unsafe + ".dll");

            string? served = AssemblyRedirect.FileFor(
                $"Some.Other.AddIn.Support, Version=1.0.0.0, Culture=neutral, {Token}", temp.Path);

            Assert.Null(served);
        }
    }

    /// <summary>
    /// The CLR asks for <c>&lt;name&gt;.resources</c> during localized lookups and expects to
    /// be told no; answering with the code assembly would be wrong even though a file of the
    /// base name is right there.
    /// </summary>
    [Fact]
    public void AResourcesRequestIsNotServed()
    {
        using (var temp = new TempFolder())
        {
            temp.Write(Unsafe + ".resources.dll");

            string? served = AssemblyRedirect.FileFor(
                $"{Unsafe}.resources, Version=6.0.0.0, Culture=fr-FR, {Token}", temp.Path);

            Assert.Null(served);
        }
    }

    /// <summary>
    /// <c>ResolveEventArgs.Name</c> is whatever asked for the assembly, and an exception
    /// thrown out of an <c>AssemblyResolve</c> handler would surface as the binding failure of
    /// whichever component happened to be loading. Unparseable names are declined, not thrown
    /// on.
    /// </summary>
    [Fact]
    public void AnUnparseableDisplayNameIsNotServed()
    {
        using (var temp = new TempFolder())
        {
            temp.Write(Unsafe + ".dll");

            Assert.Null(AssemblyRedirect.FileFor("Version=1.0.0.0, Culture=neutral", temp.Path));
        }
    }

    /// <summary>
    /// Assembly simple names are compared case-insensitively by the CLR, and the file on disk
    /// carries whatever casing the package used.
    /// </summary>
    [Fact]
    public void TheSimpleNameIsMatchedCaseInsensitively()
    {
        using (var temp = new TempFolder())
        {
            string file = temp.Write(Unsafe + ".dll");

            string? served = AssemblyRedirect.FileFor(
                $"{Unsafe.ToUpperInvariant()}, Version=4.0.4.1, Culture=neutral, {Token}", temp.Path);

            Assert.Equal(file, served, StringComparer.OrdinalIgnoreCase);
        }
    }

    /// <summary>
    /// The directory comes from the loaded add-in's location, which can be anything; a
    /// directory that is not there is declined rather than thrown on, for the same reason as
    /// the unparseable name.
    /// </summary>
    [Fact]
    public void AMissingDirectoryIsNotServed()
    {
        string missing = Path.Combine(
            Path.GetTempPath(), "SwReview.AssemblyRedirect.Tests", Guid.NewGuid().ToString("N"));
        Assert.False(Directory.Exists(missing));

        string? served = AssemblyRedirect.FileFor(
            $"{Unsafe}, Version=4.0.4.1, Culture=neutral, {Token}", missing);

        Assert.Null(served);
    }

    /// <summary>
    /// The handler is installed on the whole SOLIDWORKS AppDomain, and several assemblies
    /// beside this add-in - the seat's interops, WebView2 - are assemblies other add-ins ship
    /// too. Matching on the simple name alone would answer another add-in's failed bind for
    /// one of those with <b>this</b> add-in's copy, which is exactly what the constraint in
    /// docs/addin-load-fix.md forbids. The seat's interops are the worst case: every add-in in
    /// the process binds them, and register-addin.ps1 stages a copy beside this one.
    /// </summary>
    [Fact]
    public void AStagedSolidWorksInteropIsNotServedAlthoughTheFileIsThere()
    {
        using (var temp = new TempFolder())
        {
            temp.Write("SolidWorks.Interop.sldworks.dll");

            string? served = AssemblyRedirect.FileFor(
                "SolidWorks.Interop.sldworks, Version=31.0.0.0, Culture=neutral, "
                + "PublicKeyToken=89a97bdc5284e6d8",
                temp.Path);

            Assert.Null(served);
        }
    }

    /// <summary>
    /// Same constraint, for the dependency most likely to collide with another vendor's
    /// add-in. This add-in pins WebView2 and ships the matching file, so its own binds never
    /// fail and never reach this handler; another add-in's bind for a different version must
    /// stay that add-in's failure rather than be answered with the pinned copy.
    /// </summary>
    [Fact]
    public void AnotherAddInsWebView2BindIsNotServed()
    {
        using (var temp = new TempFolder())
        {
            temp.Write("Microsoft.Web.WebView2.Core.dll");

            string? served = AssemblyRedirect.FileFor(
                "Microsoft.Web.WebView2.Core, Version=1.0.2210.55, Culture=neutral, "
                + "PublicKeyToken=2a8ab48044d2601e",
                temp.Path);

            Assert.Null(served);
        }
    }

    /// <summary>
    /// The redirect set is the add-in's own package graph, so the assembly whose failed bind
    /// started all of this is in it, and so is the one that provokes that bind.
    /// </summary>
    [Fact]
    public void TheShimGraphThatCannotBindIsServed()
    {
        using (var temp = new TempFolder())
        {
            string json = temp.Write("System.Text.Json.dll");
            string encodings = temp.Write("System.Text.Encodings.Web.dll");

            Assert.Equal(json, AssemblyRedirect.FileFor(
                $"System.Text.Json, Version=4.0.0.0, Culture=neutral, {Token}", temp.Path));
            Assert.Equal(encodings, AssemblyRedirect.FileFor(
                $"System.Text.Encodings.Web, Version=6.0.0.0, Culture=neutral, {Token}", temp.Path));
        }
    }

    /// <summary>
    /// The directory the handler actually serves out of, which no other case reaches: it is
    /// read from <c>Assembly.CodeBase</c> through a <c>Uri</c>, and that parse is the one
    /// place the never-throw promise could have been broken. Composition rather than the pure
    /// function: the real directory, the real file beside the assembly under test.
    /// </summary>
    [Fact]
    public void TheAddInDirectoryIsTheFolderTheAssemblyWasLoadedFrom()
    {
        string directory = AssemblyRedirect.AddInDirectory;

        Assert.True(
            File.Exists(Path.Combine(directory, "SwReview.AddIn.dll")),
            $"AssemblyRedirect.AddInDirectory ('{directory}') should hold SwReview.AddIn.dll.");
        Assert.Equal(
            Path.Combine(directory, "System.Text.Json.dll"),
            AssemblyRedirect.FileFor("System.Text.Json", directory));
    }

    /// <summary>
    /// The guard, stated as behaviour: the call that subscribes reports that it did, and a
    /// second call reports that it did not, so the handler is on the AppDomain's
    /// <c>AssemblyResolve</c> exactly once however many times COM activation runs.
    /// </summary>
    [Fact]
    public void InstallingTwiceSubscribesOnce()
    {
        AssemblyRedirect.Install();

        Assert.False(AssemblyRedirect.Install());
        Assert.True(AssemblyRedirect.Installed);
    }

    /// <summary>
    /// The handler itself, on a real failed bind rather than through <see cref="FileFor"/>:
    /// a name it has no file for has to come back as the caller's own
    /// <c>FileNotFoundException</c>. An exception thrown out of the handler would surface
    /// instead, as the binding failure of whichever component happened to be loading - and in
    /// SOLIDWORKS that component is usually somebody else's add-in.
    /// </summary>
    [Fact]
    public void TheHandlerDeclinesRatherThanThrowsForANameItHasNoFileFor()
    {
        AssemblyRedirect.Install();

        Assert.Throws<FileNotFoundException>(
            () => Assembly.Load("SwReview.AssemblyRedirect.NoSuchAssembly"));
    }

    /// <summary>
    /// The wiring, which is the whole of the fix: <c>SwReviewAddIn</c>'s static constructor
    /// runs on COM activation - ahead of <c>ConnectToSW</c>, and so ahead of the first bind
    /// that fails - and it is what installs the handler. Delete that line and the add-in
    /// returns to the load failure of docs/addin-load-fix.md, cause 2.
    ///
    /// In a child AppDomain because the assertion is only worth anything on statics nothing
    /// has touched yet: this test host activates the add-in elsewhere, which would leave the
    /// redirect installed and the case passing vacuously. The child domain also gets its own
    /// <see cref="AddInLog"/>, so the checkpoint the static constructor writes lands in a
    /// temp folder instead of the engineer's real addin.log.
    /// </summary>
    [Fact]
    public void TheAddInsStaticConstructorInstallsTheHandlerAndLogsIt()
    {
        using (var temp = new TempFolder())
        {
            AppDomain domain = AppDomain.CreateDomain(
                "SwReview.AssemblyRedirect.Wiring", null, AppDomain.CurrentDomain.SetupInformation);
            try
            {
                var probe = (ActivationProbe)domain.CreateInstanceAndUnwrap(
                    typeof(ActivationProbe).Assembly.FullName, typeof(ActivationProbe).FullName);

                Assert.Equal(string.Empty, probe.RunTheAddInsClassConstructor(temp.Path));
            }
            finally
            {
                AppDomain.Unload(domain);
            }

            Assert.Contains(
                "AssemblyRedirect installed.",
                File.ReadAllText(Path.Combine(temp.Path, "addin.log")));
        }
    }

    /// <summary>
    /// Runs inside the child AppDomain of the case above. It reports a sentence rather than
    /// asserting, because an xunit failure does not cross an AppDomain boundary usefully.
    /// Public because <c>CreateInstanceAndUnwrap</c> can only activate a public type.
    /// </summary>
    public sealed class ActivationProbe : MarshalByRefObject
    {
        public string RunTheAddInsClassConstructor(string logFolder)
        {
            if (AssemblyRedirect.Installed)
            {
                return "the redirect was already installed before the add-in was activated.";
            }

            AddInLog.Folder = () => logFolder;
            RuntimeHelpers.RunClassConstructor(typeof(SwReviewAddIn).TypeHandle);

            return AssemblyRedirect.Installed
                ? string.Empty
                : "SwReviewAddIn's static constructor did not install the redirect.";
        }
    }

    private sealed class TempFolder : IDisposable
    {
        public TempFolder()
        {
            Path = System.IO.Path.Combine(
                System.IO.Path.GetTempPath(),
                "SwReview.AssemblyRedirect.Tests",
                Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path);
        }

        public string Path { get; }

        /// <summary>
        /// The resolver never opens what it finds, so the content is irrelevant and a real
        /// assembly would only make the case harder to read.
        /// </summary>
        public string Write(string name)
        {
            string full = System.IO.Path.Combine(Path, name);
            File.WriteAllText(full, "not an assembly", new UTF8Encoding(false));
            return full;
        }

        public void Dispose()
        {
            try
            {
                Directory.Delete(Path, recursive: true);
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }
    }
}
