using System;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Dump;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// Checks the native direction of drawing attachment mapping with interop stand-ins.
/// IView.GetCorrespondingEntity maps model to drawing; the owning model extension's
/// GetCorrespondingEntity2 maps an attachment back to the model. No COM object is created.
/// </summary>
public class SwDrawingReaderAttachmentTests
{
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void CorrespondingEntity_MapsThroughTheOwningModelExtension(bool edge)
    {
        var extension = new InteropRecorder<IModelDocExtension>(typeof(ModelDocExtension));
        var owner = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2)).Answer("get_Extension", extension.Instance);
        object attachment = new object();
        object model = edge
            ? new InteropRecorder<IEdge>(typeof(IEntity)).Instance
            : new InteropRecorder<IFace2>(typeof(IEntity)).Instance;
        extension.Answer("GetCorrespondingEntity2", model);
        SwDrawingReader reader = Reader(owner.Instance);

        Assert.Same(model, reader.CorrespondingEntity(owner.Instance, attachment));

        var call = Assert.Single(extension.Calls);
        Assert.Equal("GetCorrespondingEntity2", call.Member);
        Assert.Same(attachment, Assert.Single(call.Arguments));
    }

    [Fact]
    public void AnAssemblyAttachment_ResolvesItsOwnerBeforeLosingComponentContext()
    {
        var extension = new InteropRecorder<IModelDocExtension>(typeof(ModelDocExtension));
        var part = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2)).Answer("GetType", 1).Answer("get_Extension", extension.Instance);
        var assembly = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2)).Answer("GetType", 2);
        var component = new InteropRecorder<IComponent2>().Answer("GetModelDoc2", part.Instance);
        var attachment = new InteropRecorder<IFace2>(typeof(IEntity)).Answer("GetComponent", component.Instance);
        // A part-context face has no component. Ownership cannot be rediscovered on this object.
        var model = new InteropRecorder<IFace2>(typeof(IEntity))
            .Fail("GetComponent", new InvalidOperationException("Part-context entity has no component."));
        extension.Answer("GetCorrespondingEntity2", model.Instance);
        var view = new InteropRecorder<IView>().Answer("get_ReferencedDocument", assembly.Instance)
            .Fail("GetCorrespondingEntity", new InvalidOperationException("Wrong mapping direction."));
        SwDrawingReader reader = Reader(assembly.Instance);

        object? owner = reader.FaceDocument(view.Instance, attachment.Instance);
        Assert.Same(part.Instance, owner);
        Assert.Same(model.Instance, reader.CorrespondingEntity(owner!, attachment.Instance));

        Assert.Equal(new[] { "GetComponent" }, attachment.Members);
        Assert.Equal(new[] { "GetModelDoc2" }, component.Members);
        Assert.Empty(model.Members);
        Assert.DoesNotContain("GetCorrespondingEntity", view.Members);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(3)]
    [InlineData(99)]
    public void FaceDocument_DoesNotUseAnUnknownOrDrawingDocumentAsAPartScope(int kind)
    {
        var referenced = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2)).Answer("GetType", kind);
        var view = new InteropRecorder<IView>().Answer("get_ReferencedDocument", referenced.Instance);
        var attachment = new InteropRecorder<IFace2>(typeof(IEntity));

        Assert.True(Reader(referenced.Instance).FaceDocument(view.Instance, attachment.Instance) == null);
        Assert.Empty(attachment.Members);
    }

    [Fact]
    public void FaceDocument_AnAssemblyAttachmentWithoutAnEntityHasNoScope()
    {
        var assembly = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2)).Answer("GetType", 2);
        var view = new InteropRecorder<IView>().Answer("get_ReferencedDocument", assembly.Instance);

        Assert.Null(Reader(assembly.Instance).FaceDocument(view.Instance, new object()));
    }

    [Fact]
    public void FaceDocument_AnUnloadedComponentHasNoScope()
    {
        var assembly = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2)).Answer("GetType", 2);
        var component = new InteropRecorder<IComponent2>();
        var attachment = new InteropRecorder<IEdge>(typeof(IEntity)).Answer("GetComponent", component.Instance);
        var view = new InteropRecorder<IView>().Answer("get_ReferencedDocument", assembly.Instance);

        Assert.Null(Reader(assembly.Instance).FaceDocument(view.Instance, attachment.Instance));
        Assert.Equal(new[] { "GetModelDoc2" }, component.Members);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(2)]
    [InlineData(3)]
    [InlineData(99)]
    public void FaceDocument_AnAssemblyComponentWithoutAPartDocumentHasNoScope(int kind)
    {
        var assembly = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2)).Answer("GetType", 2);
        var referenced = new InteropRecorder<IModelDoc2>(typeof(ModelDoc2)).Answer("GetType", kind);
        var component = new InteropRecorder<IComponent2>().Answer("GetModelDoc2", referenced.Instance);
        var attachment = new InteropRecorder<IEdge>(typeof(IEntity)).Answer("GetComponent", component.Instance);
        var view = new InteropRecorder<IView>().Answer("get_ReferencedDocument", assembly.Instance);

        Assert.True(Reader(assembly.Instance).FaceDocument(view.Instance, attachment.Instance) == null);
    }

    private static SwDrawingReader Reader(IModelDoc2 document)
    {
        var gate = new SwGate();
        return new SwDrawingReader(new Session(document, gate), new PersistRefService(gate));
    }

    private sealed class Session : ISwSession
    {
        public Session(IModelDoc2 document, SwGate gate)
        {
            Document = document;
            Gate = gate;
        }

        public IModelDoc2 Document { get; }
        public IConfiguration? Configuration => null;
        public string? SwVersion => "2024 SP5.0";
        public SwGate Gate { get; }
    }
}
