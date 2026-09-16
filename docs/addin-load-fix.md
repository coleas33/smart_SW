# The Task Pane add-in could not load in SOLIDWORKS: three causes and their fixes

Diagnosed on a clean clone of `main`: SOLIDWORKS 2024 (interops 32.5.0.48), Windows 11,
.NET Framework 4.8, x64. Verified working in SOLIDWORKS after the changes below.

All three causes present the same symptom, which is why they are easy to mistake for one
another:

> `SwReview` appears in *Tools > Add-ins* and can be ticked, but no Task Pane appears, and
> on the next launch the check boxes are clear again.

Registration writes `HKCU\SOFTWARE\SOLIDWORKS\AddInsStartup\{GUID} = 1` for the account that
ran it — the `[ComRegisterFunction]` does it, not the engineer and not SOLIDWORKS — so after
a successful registration the box starts out ticked. SOLIDWORKS clears that flag to `0` when
an add-in fails to load, so **the reverting check box is the error message**, and so is a box
that is clear the first time it is looked at. (The one innocent explanation: the elevated
prompt ran as a different account, and the flag is in that account's hive.) Before the change
in "Why this took so long to find" below, nothing was written under
`%LOCALAPPDATA%\SwReview\logs` either, because the failure happened ahead of any code that
logs.

They block in this order: registration (cause 3), then load (cause 1), then the first
settings read (cause 2).

---

## Cause 1: `ClassInterfaceType.None` leaves the add-in with no `IDispatch`

**This is the primary blocker. It is machine-independent — the add-in as written could not
load anywhere.**

### Evidence

With load-progress logging added to `ConnectToSW` (the diagnostic build's wording; see
"the two decisions taken when this was merged" below for the lines that shipped):

```
static ctor: AssemblyRedirect installed
ConnectToSW entered
cast to ISldWorks ok
FAILED before the pane: System.InvalidCastException: Specified cast is not valid.
   at System.StubHelpers.InterfaceMarshaler.ConvertToNative(Object objSrc, IntPtr itfMT, IntPtr classMT, Int32 flags)
   at SolidWorks.Interop.sldworks.ISldWorks.SetAddinCallbackInfo2(Int64 ModuleHandle, Object AddinCallbacks, Int32 Cookie)
   at SwReview.AddIn.SwReviewAddIn.ConnectToSW(Object ThisSW, Int32 Cookie)
```

The assembly loads and the `(ISldWorks)ThisSW` cast succeeds. The failure is marshalling
**the add-in itself** into `SetAddinCallbackInfo2`.

Reproduced in isolation, against the built assembly, with no SOLIDWORKS involved:

| Call on a `new SwReviewAddIn()` | Result |
| --- | --- |
| `Marshal.GetIUnknownForObject` | OK |
| `Marshal.GetIDispatchForObject` | **InvalidCastException: "Specified cast is not valid."** |

Same exception, same message as the in-process failure.

### Root cause

`SetAddinCallbackInfo2`'s `AddinCallbacks` parameter marshals as `IDispatch` — that is how
SOLIDWORKS invokes Task Pane and command callbacks, late bound by name. The class was
declared:

```csharp
[ClassInterface(ClassInterfaceType.None)]
```

`None` generates no class interface, so the COM-callable wrapper exposes `IUnknown` and the
explicitly implemented `ISwAddin`, but **no `IDispatch`**. The marshaller therefore cannot
convert the instance for that argument, and throws.

### Fix

```csharp
[ClassInterface(ClassInterfaceType.AutoDispatch)]
```

`AutoDispatch` is the framework default and supplies the late-bound `IDispatch` SOLIDWORKS
needs. `AutoDual` also works and is what several add-in templates use, but it additionally
bakes a v-table class interface that this add-in has no need to version, so `AutoDispatch`
is the smaller promise.

No re-registration is required: the CLSID, ProgID and codebase are unchanged.

### Tests

`extractor/SwReview.AddIn.Tests/AddInComCallbackTests.cs` (3 cases):

- `TheAddInCanBeMarshalledAsAnIDispatchCallbackTarget` — calls `Marshal.GetIDispatchForObject`,
  which is exactly what the marshaller does to the callback argument. **This is the regression.**
- `TheAddInDoesNotSuppressItsClassInterface` — states the requirement as the attribute, so the
  reason survives even if the marshalling test is later weakened.
- `TheAddInIsComVisible` — the precondition for either of the above to matter.

Confirmed failing before the attribute change (2 of 3 failed, `ComVisible` passed) and
passing after.

These cases name `SwReviewAddIn`, whose base interface `ISwAddin` lives in
`SolidWorks.Interop.swpublished`, so that interop is now referenced by
`SwReview.AddIn.Tests.csproj` with `Private=true` alongside `sldworks` and `swconst`. Without
it all three failed on `FileNotFoundException` instead — a red for the wrong reason.

---

## Cause 2: `System.Runtime.CompilerServices.Unsafe` cannot bind in a host with no config

Reachable only once cause 1 is fixed, and it sits on the same `ConnectToSW` path:
`CreateTaskPane` calls `UserSettings.Load`, which is the first use of `System.Text.Json`.

### Root cause

The add-in's dependencies disagree about which `Unsafe` they want, and only one file of a
given name can ship beside the add-in:

| Assembly beside the add-in | Version | References `Unsafe` |
| --- | --- | --- |
| `System.Memory` | 4.0.1.2 | **4.0.4.1** |
| `System.Threading.Tasks.Extensions` | 4.2.0.1 | **4.0.4.1** |
| `System.Text.Json` | 8.0.0.5 | **6.0.0.0** |
| `System.Text.Encodings.Web` | 8.0.0.0 | **6.0.0.0** |
| `System.Runtime.CompilerServices.Unsafe` | **6.0.0.0** | — |

On .NET Framework this is reconciled by a `<bindingRedirect>` in the **host's**
`.exe.config`. `SLDWORKS.exe` ships no config, so the 4.0.4.1 request fails:

```
TypeInitializationException: System.Text.Json.JsonSerializer
  -> TypeInitializationException: PerTypeValues`1
    -> FileNotFoundException: Could not load file or assembly
       'System.Runtime.CompilerServices.Unsafe, Version=4.0.4.1, Culture=neutral,
        PublicKeyToken=b03f5f7f11d50a3a'
```

### Why the suite never caught it

`extractor/SwReview.AddIn.Tests/SwReview.AddIn.Tests.csproj` sets:

```xml
<AutoGenerateBindingRedirects>true</AutoGenerateBindingRedirects>
```

The test host has exactly the redirects the real host lacks. `UserSettingsTests` round-trips
JSON happily, so the full suite passed against a build that could not read its own settings
inside SOLIDWORKS. Any test that exercises this dependency graph *inside the test host* is
structurally incapable of catching it.

### Fix

New file `extractor/SwReview.AddIn/AssemblyRedirect.cs`: an `AppDomain.AssemblyResolve`
handler that answers a failed bind with the file of the same **simple name** beside the
add-in, ignoring the requested version. That is what a binding redirect does, and the CLR
accepts an assembly returned from this event whose version does not match the request —
ordinary probing would refuse it.

Installed from a static constructor, which runs on COM activation, ahead of `ConnectToSW`:

```csharp
static SwReviewAddIn()
{
    AssemblyRedirect.Install();
    Log("AssemblyRedirect installed.");
}
```

Three constraints the handler respects, because this event fires for **every** failed bind in
the SOLIDWORKS process, including other add-ins':

- it answers only a **named set** of simple names — the managed assemblies this add-in's own
  NuGet graph puts beside it, listed in `AssemblyRedirect.Redirected` — and only when the name
  is also a file in the add-in's own folder. The name alone is not enough: the output folder
  also holds the seat's `SolidWorks.Interop.*`, staged there by `register-addin.ps1` and bound
  by every add-in in the process, and WebView2, which several add-ins ship. Answering one of
  those would take over another add-in's binding. A dependency added later that cannot bind in
  a config-less host has to be named in that set; the blast radius is one list;
- it declines `<name>.resources` requests, which the CLR makes during localized lookups and
  expects to be told no;
- every substitution it does serve is written to `addin.log`, because a redirect this handler
  served to something that is not this add-in must not be silent.

The residual, stated plainly: for the shim names in the set, a bind from elsewhere in the
process for an older version *is* answered with this add-in's copy. That is what a host-wide
`bindingRedirect` would have done, it is confined to nine Microsoft assemblies the add-in
ships anyway, and the log line names every occurrence.

The handler never throws — not just `FileFor`: an exception out of an `AssemblyResolve`
handler would surface as the binding failure of whichever component happened to be loading,
which in this process is usually somebody else's add-in. The one expression on that path that
could throw is the add-in's own directory (`Assembly.CodeBase` through a `Uri`), so it is
resolved once in the type initializer, guarded, falling back to the empty string that
`FileFor` already declines.

### Why a resolve handler rather than a config or the GAC

| Option | Verdict |
| --- | --- |
| `AssemblyResolve` handler in the add-in | **Chosen.** Travels with the add-in, needs no elevation, does not modify the SOLIDWORKS installation, survives service packs, unit-testable. |
| Author `SLDWORKS.exe.config` with redirects | Rejected. Modifies a vendor installation, needs admin per workstation, affects SOLIDWORKS' own managed code and every other add-in, erased by updates. |
| GAC-install the shim assemblies | Rejected. Machine-wide state, admin per workstation, and nothing in the repo would record that it is required. |
| Ship a matching `Unsafe` version | Impossible. Two consumers want different versions; only one file of that name can sit beside the add-in. |

### Tests

`extractor/SwReview.AddIn.Tests/AssemblyRedirectTests.cs` (15 cases).

Eleven assert the resolver as a **pure function** of a display name and a directory
(`AssemblyRedirect.FileFor`) rather than by loading anything, precisely because the test host's
own binding policy would otherwise mask the behaviour: an older-version request served by the
newer file on disk (the regression), a newer-version request and a request with no version at
all served by that same file — the version is ignored, not compared — an unknown name not
served, a `.resources` request not served, an unparseable display name returning null instead
of throwing, case-insensitive matching, a missing directory not served, the two names outside
the redirect set that *do* sit beside the add-in (a staged `SolidWorks.Interop.sldworks` and
another add-in's WebView2) not served although the file is there, and `System.Text.Json` with
`System.Text.Encodings.Web` served.

Four reach past the pure function, because a correct predicate wired to nothing is still the
load failure this document diagnoses:

- `TheAddInDirectoryIsTheFolderTheAssemblyWasLoadedFrom` — the `CodeBase`/`Uri` path, which no
  pure-function case executes, and the file it finds beside the assembly under test.
- `InstallingTwiceSubscribesOnce` — `Install` reports whether it subscribed, and the second
  call says it did not.
- `TheHandlerDeclinesRatherThanThrowsForANameItHasNoFileFor` — a real failed bind through the
  installed handler comes back as the caller's own `FileNotFoundException`.
- `TheAddInsStaticConstructorInstallsTheHandlerAndLogsIt` — the wiring, in a **child
  AppDomain** so that nothing has installed the handler yet and the case cannot pass
  vacuously: running `SwReviewAddIn`'s class constructor there leaves the redirect installed
  and the checkpoint in the log. Verified by mutation — with `AssemblyRedirect.Install()`
  removed from the static constructor, this is the one case of 395 that fails.

### How to verify in a redirect-free host

Unit tests cannot prove this, because they run *with* redirects. Windows PowerShell is a
faithful host: it has a `.config` but no `bindingRedirect` entries (verified — zero matches in
`powershell.exe.Config`). Run each half in its own process; once the redirect is installed it
stays installed for the life of the AppDomain. `settings.json` has to exist, or `Load` returns
the defaults for a first run without ever reaching `System.Text.Json`.

Control — touch only `UserSettings`, so the static constructor never runs:

```powershell
$dir = "<repo>\extractor\SwReview.AddIn\bin\x64\Release\net48"
$asm = [System.Reflection.Assembly]::LoadFrom((Join-Path $dir "SwReview.AddIn.dll"))
$t = $asm.GetType("SwReview.AddIn.Settings.UserSettings")
[string]$path = "<a settings.json that exists>"
try { $t.GetMethod("Load", [type[]]@([string])).Invoke($null, [object[]]@([string]$path)) }
catch { $e = $_.Exception; while ($e.InnerException) { $e = $e.InnerException }; $e.Message }
```

Observed:

```
System.IO.FileNotFoundException: Could not load file or assembly
'System.Runtime.CompilerServices.Unsafe, Version=4.0.4.1, Culture=neutral,
 PublicKeyToken=b03f5f7f11d50a3a' or one of its dependencies. The system cannot find the file specified.
```

Treatment — run the type initializer first, which is what COM activation does:

```powershell
$addin = $asm.GetType("SwReview.AddIn.SwReviewAddIn")
[System.Runtime.CompilerServices.RuntimeHelpers]::RunClassConstructor($addin.TypeHandle)
# then call UserSettings.Load as above
```

Observed:

```
TREATMENT: Load returned with no error (SwReview.AddIn.Settings.SettingsLoadResult)
```

`GetType("SwReview.AddIn.SwReviewAddIn")` returns `null` unless the seat's interops are beside
the add-in, because the type names `ISwAddin`. Stage them first — that is step 1 of
`register-addin.ps1`, and it is cause 3.

---

## Cause 3: `regasm` cannot resolve the seat's interops (registration)

### Evidence

```
RegAsm : error RA0000 : Could not load file or assembly
'SolidWorks.Interop.swpublished, Version=32.5.0.48, Culture=neutral,
 PublicKeyToken=89a97bdc5284e6d8' or one of its dependencies.
```

### Root cause

`regasm` must load `swpublished` to reflect over `ISwAddin` while registering. The interops
live in `<install>\api\redist`, which is not on any assembly probing path, and
`SwReview.AddIn.csproj` sets `<Private>false</Private>` so the build does not copy them.
Adding `api\redist` to `PATH` does nothing — assembly binding ignores `PATH`.

### Fix

`extractor/tools/register-addin.ps1`, new and tracked. It copies
`SolidWorks.Interop.{sldworks,swconst,swpublished}.dll` from the seat's `api\redist` into the
add-in's output folder and then runs the 64-bit `regasm /codebase`; `-Unregister` runs
`regasm /unregister` instead, staging the same files first because `/unregister` reflects over
the assembly too. `-SolidWorksRoot` defaults to the standard install location and
`-Configuration` to `Release`. It refuses to run non-elevated, before copying anything, so a
non-elevated run changes nothing rather than half of it, and it prints each file it staged and
the exact `regasm` command it ran.

This is not redistribution: they are copies from the local installation, on a machine that
already has the seat, and `extractor/**/bin/` is not tracked.

The three files are byte-identical to the copies in the SOLIDWORKS install root (same SHA-256,
same MVID, same `ISldWorks` IID `83a33d22-27c5-11ce-bfd4-00400513bb57`), so there is no
duplicate-type hazard in keeping them beside the add-in.

The registration steps in the `SwReviewAddIn` class comment, `extractor/README.md` and
`specs/002-task-pane-assistant/quickstart.md` now give the script rather than a bare
`regasm /codebase SwReview.AddIn.dll`, which cannot succeed on a clean build, and each names
the staging step and why it exists.

They also no longer say that the engineer ticks the box afterwards. `RegisterFunction` writes
`HKCU\...\AddInsStartup\{GUID} = 1` as well as the HKLM keys, so a successful registration
leaves SwReview enabled for the account that ran the script, and the box is expected to be
ticked on the next start. That sentence matters more than it looks: told to tick the box
first, an engineer reads a *cleared* box after a clean registration as a step still to do
rather than as the load failure it is — and the reverting check box is the only signal this
whole document exists to make legible.

*Not established:* whether the interops are also required beside the add-in at **run time**.
The SOLIDWORKS install root carries them and is the app base, so it may well satisfy the
runtime bind on its own. They were present for every successful load here, and were not
isolated as a variable once cause 1 was known.

---

## Why this took so long to find: the silent failure

The two statements at the top of `ConnectToSW` ran outside any guard:

```csharp
_swApp = (ISldWorks)ThisSW;
_addInCookie = Cookie;
_swApp.SetAddinCallbackInfo2(0, this, _addInCookie);
```

The class comment already stated the intent — *"Neither failure may leave ConnectToSW"* — but
it was only honoured for `CreateTaskPane` and `StartReviewHost`. An exception in the lines
above escaped the method, SOLIDWORKS cleared the startup flag, and `Report` was never reached,
so **no log existed anywhere**. Every cause above therefore produced an identical, evidenceless
symptom.

Those statements are now wrapped in a third guard, so the same class of failure reports itself
through `Report` into `%LOCALAPPDATA%\SwReview\logs\addin.log` and returns `false` rather than
claiming a successful load.

### The two decisions taken when this was merged

**Load-progress lines are kept, and they go in `addin.log`.** The diagnostic build wrote
per-step `Trace(...)` checkpoints to a separate `connect.log` and marked them
`DIAGNOSTIC (temporary)`. Neither survived. There is one log, `addin.log`, and one helper —
`AddInLog.Write` — appends a timestamped line to it; `SwReviewAddIn.Log`, `Report` and
`AssemblyRedirect` all write through that same helper, so there is a single mechanism and a
single file. Four checkpoints are written — the static
constructor installing the redirect, the attach, the pane, the review host — plus whatever
`Report` records for a failure and a line per assembly substitution. The reason to keep them:
an add-in load failure is otherwise silent by construction, and four lines a session turns
"it did not load" into a named step.

`AddInLog` is a type of its own, with the log folder behind an injectable `Func<string>`, for
one reason that is worth stating: without it the unit suite wrote into the engineer's real
`addin.log`. `AddInComCallbackTests` constructs the add-in, which runs the type initializer,
which logs; five `dotnet test` runs left five timestamped `AssemblyRedirect installed.` lines
in `%LOCALAPPDATA%\SwReview\logs\addin.log`, indistinguishable from real SOLIDWORKS
activations, in the one file this document tells an engineer to trust. The seam cannot live on
`SwReviewAddIn` itself: assigning a static field on that class would run the very type
initializer whose line is being redirected.

**The registration script is added rather than only documented.** A machine-local script was
in use during the diagnosis but lived under `bin/` and was untracked, which is how the staging
step went missing from the documented steps in the first place.

---

## Diagnostic notes worth keeping

**Failed by-name binds in the Fusion log are benign.** When mscoree activates a
`/codebase`-registered add-in, it first attempts a by-name bind that probes only the app base
and fails; it then loads from `CodeBase`, and successes are not logged. SOLIDWORKS' own
`SWPDFTaskAddIn` and the third-party `SW2URDF` produce the identical failure entry while
working correctly. Do not read those entries as the cause.

**A locked DLL proves the assembly loaded.** If `dotnet build` reports
`The file is locked by: "SolidWorks (<pid>)"`, SOLIDWORKS has the assembly open — which rules
out any binding theory for the add-in assembly itself. SOLIDWORKS must be closed to rebuild.

**Do not diagnose COM marshalling through PowerShell.** Calling `ConnectToSW` on a COM RCW
from PowerShell raises `InvalidCastException` because PowerShell wraps arguments in `PSObject`.
That looks exactly like the real bug and is unrelated to it. Confirm interface support with
`Marshal.QueryInterface` against the IID instead; for the live SOLIDWORKS object,
`IID_ISldWorks` returns `0x00000000`.

---

## Files changed

| File | Change |
| --- | --- |
| `extractor/SwReview.AddIn/SwReviewAddIn.cs` | `ClassInterfaceType.AutoDispatch` (cause 1); static constructor installing the resolver (cause 2); a third guard with `Report` around the attach statements, returning `false`; `Log` load checkpoints into `addin.log`; registration steps in the class comment |
| `extractor/SwReview.AddIn/AssemblyRedirect.cs` | new — the resolve handler |
| `extractor/SwReview.AddIn/AddInLog.cs` | new — the one log file, behind an injectable folder |
| `extractor/SwReview.AddIn.Tests/AddInComCallbackTests.cs` | new — 3 cases, cause 1; points `AddInLog` at a temp folder so the suite does not write into the real `addin.log` |
| `extractor/SwReview.AddIn.Tests/AssemblyRedirectTests.cs` | new — 15 cases, cause 2 |
| `extractor/SwReview.AddIn.Tests/SwReview.AddIn.Tests.csproj` | `SolidWorks.Interop.swpublished` reference, so the add-in type can be named |
| `extractor/tools/register-addin.ps1` | new — stage the interops, `regasm /codebase`, `-Unregister` |
| `extractor/README.md`, `specs/002-task-pane-assistant/quickstart.md` | registration steps use the script, name the staging, and say that registration is what enables the add-in |
| `docs/addin-load-fix.md` | new — this document |

This change contributes **18** cases to the add-in suite (3 for cause 1, 15 for cause 2), and
the whole suite passes with them.
