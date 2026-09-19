using System;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// What <see cref="SwSession.Attach"/> refuses before it asks for a configuration.
///
/// The failure this targets: SOLIDWORKS was loaded with a drawing active, the add-in attached
/// to whatever was open, and every drawing answers null to
/// <c>ConfigurationManager.ActiveConfiguration</c>. The session then failed with "reports no
/// active configuration", which names a symptom and no action - and because the tool service
/// swallows a failed start into addin.log, every bridge-backed feature was silently off for
/// the session.
///
/// Attaching is what needs the configuration, not the document: the manifest, the reuse key
/// and every dumper are bound to one. So a drawing is refused by name, with the document to
/// open instead. Choosing that sentence is pure and is testable here; making the call that
/// discovers the kind needs SOLIDWORKS and is not.
/// </summary>
public class SwSessionAttachTests
{
    private const string Drawing = @"C:\vault\810-11471.SLDDRW";

    [Fact]
    public void AttachRefusal_ADrawingIsRefusedByNameWithTheDocumentToOpenInstead()
    {
        string? refusal = SwSession.AttachRefusal(DocumentKind.Drawing, Drawing);

        Assert.NotNull(refusal);
        Assert.Contains(Drawing, refusal!, StringComparison.Ordinal);
        Assert.Contains("drawing", refusal, StringComparison.Ordinal);
        Assert.Contains("open the part or assembly", refusal, StringComparison.Ordinal);
    }

    [Fact]
    public void AttachRefusal_DoesNotFallBackToTheSentenceThatNamedNoCause()
    {
        // The old message. A drawing reaching it again would mean the kind test was lost, and
        // the engineer would be back to a symptom with no action in it.
        Assert.DoesNotContain(
            "reports no active configuration",
            SwSession.AttachRefusal(DocumentKind.Drawing, Drawing)!,
            StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(DocumentKind.Part)]
    [InlineData(DocumentKind.Assembly)]
    public void AttachRefusal_WhatTheExtractorIsForIsNotRefused(DocumentKind kind)
    {
        // The refusal is one document kind wide. A part or an assembly that reports no
        // configuration is a different failure and keeps its own message.
        Assert.Null(SwSession.AttachRefusal(kind, @"C:\vault\810-11471.SLDPRT"));
    }
}
