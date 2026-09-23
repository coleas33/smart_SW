using System;
using System.Collections.Generic;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Dump;

/// <summary>
/// The reads of a geometric tolerance's frames and datum identifier and of a datum tag's label,
/// with no interop type in the signature: the part of feature 010's
/// <see cref="IModelAnnotationReader"/> that a drawing's typed annotations are read through too
/// (feature 011, contracts/native-evidence.md section 3), so the model and the drawing read a GTol
/// through one set of members.
/// </summary>
public interface IAnnotationSymbolReads
{
    /// <summary><c>IAnnotation.GetSpecificAnnotation</c>: the IGtol, IDatumTag or ISFSymbol.</summary>
    object? Specific(object annotation);

    /// <summary><c>IGtol.GetFrameCount</c>.</summary>
    int FrameCount(object gtol);

    /// <summary><c>IGtol.GetFrameValues(frame)</c> as strings; null when it answers nothing.</summary>
    IReadOnlyList<string>? FrameValues(object gtol, int frame);

    /// <summary><c>IGtol.GetFrameSymbols3(frame)</c> as strings; null when it answers nothing.</summary>
    IReadOnlyList<string>? FrameSymbols(object gtol, int frame);

    /// <summary><c>IGtol.GetFrame(frame)</c> then <c>IGtolFrame.GetSymbolXml</c>; null for the pre-2022 format.</summary>
    string? FrameXml(object gtol, int frame);

    /// <summary><c>IGtol.GetDatumIdentifier</c>.</summary>
    string? DatumIdentifier(object gtol);

    /// <summary><c>IDatumTag.GetLabel</c>.</summary>
    string? DatumLabel(object datumTag);
}

/// <summary>
/// Feature 010's reading of one GTol frame, extracted so the model's <c>tolerance</c> phase and a
/// drawing's geometric tolerances share it (feature 011 T040, "one annotation record"): the frame
/// asked both ways - the pre-2022 calls and the 2022 format's XML - since the API answers each for
/// one generation of GTol only.
/// </summary>
public static class GtolFrames
{
    /// <summary>
    /// Frame <paramref name="frame"/> of <paramref name="gtol"/>, kept with whatever answered; null
    /// when no call answered, with each call's failure added to <paramref name="errors"/> for the
    /// caller's one gap. A guard refusal or an open circuit is not a GTol format, and ends the dump.
    /// </summary>
    public static GtolFrame? Read(
        SwGate gate, IAnnotationSymbolReads reads, object gtol, int frame, List<string> errors)
    {
        if (gate == null)
        {
            throw new ArgumentNullException(nameof(gate));
        }

        if (reads == null)
        {
            throw new ArgumentNullException(nameof(reads));
        }

        if (errors == null)
        {
            throw new ArgumentNullException(nameof(errors));
        }

        IReadOnlyList<string>? values = Optional(
            errors, () => gate.CallOptional("GetFrameValues", () => reads.FrameValues(gtol, frame)));
        IReadOnlyList<string>? symbols = Optional(
            errors, () => gate.CallOptional("GetFrameSymbols3", () => reads.FrameSymbols(gtol, frame)));
        string? xml = Optional(errors, () => HoleDumper.Blank(reads.FrameXml(gtol, frame)));

        bool answered = (values != null && values.Count > 0) || (symbols != null && symbols.Count > 0) || xml != null;
        if (!answered)
        {
            return null;
        }

        var read = new GtolFrame { Number = frame, SymbolXmlRaw = xml };
        if (values != null)
        {
            read.ValuesRaw.AddRange(values);
        }

        if (symbols != null)
        {
            read.SymbolsRaw.AddRange(symbols);
        }

        return read;
    }

    /// <summary>
    /// One frame read whose failure is expected for one GTol format: the error is kept for the
    /// frame's gap and the answer is null. A guard refusal or an open circuit is not a format.
    /// </summary>
    private static T? Optional<T>(List<string> errors, Func<T?> read)
        where T : class
    {
        try
        {
            return read();
        }
        catch (CircuitOpenError)
        {
            throw;
        }
        catch (MutatingCallError)
        {
            throw;
        }
        catch (Exception ex)
        {
            errors.Add(GapCollector.Describe(ex));
            return null;
        }
    }
}
