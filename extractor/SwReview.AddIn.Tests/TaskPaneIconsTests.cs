using System;
using System.Drawing;
using System.IO;
using System.Linq;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// The Task Pane tab icon. SOLIDWORKS' <c>CreateTaskpaneView3</c> takes one PNG per size and
/// picks by display scaling, so the add-in hands it the six files under <c>Icons\</c> beside
/// the add-in - or, when any one of them is missing, nothing, and <see cref="SwReviewAddIn"/>
/// falls back to the stock icon rather than to no tab. Two things are asserted: the resolver
/// as a pure function of a directory, and that the build actually put six PNGs of the named
/// sizes where the resolver looks, because a csproj that stopped copying them would otherwise
/// surface only as a stock icon on the workstation.
/// </summary>
public sealed class TaskPaneIconsTests
{
    [Fact]
    public void TheSixSizesResolveInTheOrderSolidworksWants()
    {
        using (var temp = new IconFolder())
        {
            foreach (int size in TaskPaneIcons.Sizes)
            {
                temp.Write(size);
            }

            string[]? paths = TaskPaneIcons.Resolve(temp.AddInDirectory);

            Assert.NotNull(paths);
            Assert.Equal(new[] { 20, 32, 40, 64, 96, 128 }, TaskPaneIcons.Sizes);
            Assert.Equal(
                new[]
                {
                    "taskpane-20.png", "taskpane-32.png", "taskpane-40.png",
                    "taskpane-64.png", "taskpane-96.png", "taskpane-128.png",
                },
                paths!.Select(Path.GetFileName));
            Assert.All(paths!, path => Assert.Equal(
                Path.Combine(temp.AddInDirectory, "Icons"), Path.GetDirectoryName(path)));
        }
    }

    /// <summary>
    /// All six or none: SOLIDWORKS is handed the whole set, and a set with a hole would be a
    /// tab that draws at some scalings and not others.
    /// </summary>
    [Theory]
    [InlineData(20)]
    [InlineData(32)]
    [InlineData(40)]
    [InlineData(64)]
    [InlineData(96)]
    [InlineData(128)]
    public void AMissingSizeMeansNoIconSet(int missing)
    {
        using (var temp = new IconFolder())
        {
            foreach (int size in TaskPaneIcons.Sizes.Where(size => size != missing))
            {
                temp.Write(size);
            }

            Assert.Null(TaskPaneIcons.Resolve(temp.AddInDirectory));
        }
    }

    /// <summary>
    /// The empty string is what <see cref="AssemblyRedirect.AddInDirectory"/> is when the
    /// add-in's folder cannot be named; an absent folder is a deploy that dropped it.
    /// </summary>
    [Fact]
    public void AnUnnamedOrAbsentDirectoryMeansNoIconSet()
    {
        Assert.Null(TaskPaneIcons.Resolve(string.Empty));
        Assert.Null(TaskPaneIcons.Resolve(Path.Combine(
            Path.GetTempPath(), "SwReview.TaskPaneIcons.Tests", Guid.NewGuid().ToString("N"))));
    }

    /// <summary>
    /// The build step, not the resolver: SwReview.AddIn.csproj copies <c>Icons\*.png</c> to
    /// the output folder, which flows to this test host's folder the same way the add-in
    /// itself does. Each file is opened, so a wrong-sized or non-PNG file fails here rather
    /// than as a blank tab.
    /// </summary>
    [Fact]
    public void TheBuildPutsSixRealPngsOfTheNamedSizesBesideTheAddIn()
    {
        string[]? paths = TaskPaneIcons.Resolve(AssemblyRedirect.AddInDirectory);

        Assert.True(
            paths != null,
            $"no Icons folder with the six PNGs under '{AssemblyRedirect.AddInDirectory}'; "
            + "SwReview.AddIn.csproj should copy Icons\\*.png to the output folder.");
        for (int i = 0; i < paths!.Length; i++)
        {
            using (Image image = Image.FromFile(paths[i]))
            {
                Assert.Equal(new Size(TaskPaneIcons.Sizes[i], TaskPaneIcons.Sizes[i]), image.Size);
            }
        }
    }

    /// <summary>
    /// A stand-in add-in folder with an <c>Icons</c> subfolder. The resolver never opens what
    /// it finds, so the files are empty.
    /// </summary>
    private sealed class IconFolder : IDisposable
    {
        public IconFolder()
        {
            AddInDirectory = Path.Combine(
                Path.GetTempPath(), "SwReview.TaskPaneIcons.Tests", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path.Combine(AddInDirectory, "Icons"));
        }

        public string AddInDirectory { get; }

        public void Write(int size)
        {
            File.WriteAllBytes(
                Path.Combine(AddInDirectory, "Icons", TaskPaneIcons.FileName(size)), new byte[0]);
        }

        public void Dispose()
        {
            try
            {
                Directory.Delete(AddInDirectory, recursive: true);
            }
            catch (IOException)
            {
            }
        }
    }
}
