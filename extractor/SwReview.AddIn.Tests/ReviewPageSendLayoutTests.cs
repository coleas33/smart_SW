using System;
using System.Text.Json;
using Xunit;
using Xunit.Abstractions;

namespace SwReview.AddIn.Tests;

/// <summary>T056 acceptance on the real backend's waiting big assembly, after page code.</summary>
public sealed class ReviewPageSendLayoutTests
{
    private readonly ITestOutputHelper _output;

    public ReviewPageSendLayoutTests(ITestOutputHelper output) { _output = output; }

    [Fact]
    public void TheHeadlineTallyNotReachedAndSendAreInsideThe300By600Viewport()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read("review-waiting-big-assembly.json");
        ReviewPageDriver.Run(fixture.Configure, async driver =>
        {
            await fixture.Start(driver);
            await ReviewPageSummaryAcceptanceTests.NarrowPane(driver);
            JsonElement measured = await driver.Read(ReadGeometry);
            _output.WriteLine(measured.GetRawText());
            Assert.True(measured.GetProperty("headlineInView").GetBoolean(), measured.ToString());
            Assert.True(measured.GetProperty("tallyInView").GetBoolean(), measured.ToString());
            Assert.True(measured.GetProperty("notReachedInView").GetBoolean(), measured.ToString());
            Assert.True(measured.GetProperty("sendInView").GetBoolean(), measured.ToString());
            Assert.True(measured.GetProperty("sendSlack").GetDouble() >= 0, measured.ToString());
        });
    }

    /// <summary>T077 acceptance on the backend's actual failed first-request snapshot;
    /// authored only after complete T075 green, with every page/shared asset held unchanged.</summary>
    [Fact]
    public void AFailedSendKeepsTheHeadlineTallyNotReachedAndSendInside300By600()
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read("review-waiting-big-assembly.json");
        JsonElement failed = fixture.Root.GetProperty("failed_send");
        string expectedFailure = failed.GetProperty("ranking").GetProperty("summary").GetProperty("send").GetProperty("failure").GetString()!;
        Assert.False(string.IsNullOrWhiteSpace(expectedFailure));
        Assert.Equal("awaiting_send", failed.GetProperty("chat_state").GetString());
        ReviewPageDriver.Run(driver =>
        {
            fixture.Configure(driver);
            driver.InitialRoutes.RemoveAll(route => route.Path == "/sessions/chat-1/snapshot");
            driver.InitialRoutes.Add(("GET", "/sessions/chat-1/snapshot", 200, failed.GetRawText()));
        }, async driver =>
        {
            await ReviewPageSummaryAcceptanceTests.NarrowPane(driver);
            JsonElement measured = await driver.Read(ReadGeometry);
            JsonElement failure = await driver.Read(@"
var line=document.querySelector('#send .note.bad');
return JSON.stringify({ok:true,text:line?line.textContent:null,rendered:h.rendered(line),
 failureInView:h.inView(line),failureSlack:line?window.innerHeight-line.getBoundingClientRect().bottom:null,
 errorCard:!!document.querySelector('#errors .card.error')});");
            _output.WriteLine("SC007 " + measured.GetRawText());
            _output.WriteLine("Failure " + failure.GetRawText());
            Assert.Equal(expectedFailure, failure.GetProperty("text").GetString());
            Assert.True(failure.GetProperty("rendered").GetBoolean());
            Assert.False(failure.GetProperty("errorCard").GetBoolean());
            Assert.True(measured.GetProperty("headlineInView").GetBoolean(), measured.ToString());
            Assert.True(measured.GetProperty("tallyInView").GetBoolean(), measured.ToString());
            Assert.True(measured.GetProperty("notReachedInView").GetBoolean(), measured.ToString());
            Assert.True(measured.GetProperty("sendInView").GetBoolean(), measured.ToString());
            Assert.True(measured.GetProperty("sendSlack").GetDouble() >= 0, measured.ToString());
            // Read-only diagnostic requested after acceptance: ordinary Results scrolling
            // must reveal the whole failure note, without changing any page asset or style.
            JsonElement scrolled = await driver.Read(@"
var line=document.querySelector('#send .note.bad');var scroller=line.parentElement;
while(scroller && ['auto','scroll'].indexOf(getComputedStyle(scroller).overflowY)<0)scroller=scroller.parentElement;
if(!scroller)throw new Error('failure has no scrolling ancestor');
var before=scroller.scrollTop;var clipBottom=scroller.getBoundingClientRect().bottom;
var originalBottom=line.getBoundingClientRect().bottom;
scroller.scrollTop+=Math.max(0,originalBottom-clipBottom)+1;
return JSON.stringify({ok:true,text:line.textContent,wholeNoteInView:h.inView(line),
 scrollerId:scroller.id,scrollTopBefore:before,scrollTopAfter:scroller.scrollTop,
 initialClipBottom:clipBottom,initialNoteBottom:originalBottom,noteBottomAfter:line.getBoundingClientRect().bottom});");
            _output.WriteLine("Scroll " + scrolled.GetRawText());
            Assert.Equal(expectedFailure, scrolled.GetProperty("text").GetString());
            Assert.True(scrolled.GetProperty("wholeNoteInView").GetBoolean(), scrolled.ToString());
        });
    }

    [Theory]
    [InlineData(260)]
    [InlineData(300)]
    [InlineData(420)]
    public void TheSessionButtonsWrapAndTheBoxSitsDirectlyBelowThem(int width)
    {
        WaitingReviewFixture fixture = WaitingReviewFixture.Read("review-waiting-big-assembly.json");
        ReviewPageDriver.Run(fixture.Configure, async driver =>
        {
            await fixture.Start(driver);
            await driver.Page.CallDevToolsProtocolMethodAsync("Emulation.setDeviceMetricsOverride",
                JsonSerializer.Serialize(new { width, height = 600, deviceScaleFactor = 1, mobile = false }));
            await driver.Settle();
            JsonElement measured = await driver.Read(ReadGeometry);
            _output.WriteLine(measured.GetRawText());
            Assert.True(measured.GetProperty("boxAfterButtons").GetBoolean(), measured.ToString());
            Assert.True(measured.GetProperty("noHorizontalOverflow").GetBoolean(), measured.ToString());
            if (width == 300) Assert.Equal(2, measured.GetProperty("buttonRows").GetInt32());
            Assert.True(measured.GetProperty("boxTop").GetDouble() >= measured.GetProperty("buttonBottom").GetDouble(), measured.ToString());
        });
    }

    internal const string ReadGeometry = @"
h.resetScroll();
var summary=document.getElementById('summary');
var send=document.querySelector('#send [data-action=send]');
var box=document.querySelector('label.send-when-checked');
var row=document.querySelector('#session > .row');
var buttons=row.querySelectorAll('button');
var tops=[];
for(var i=0;i<buttons.length;i++) {
 var top=buttons[i].getBoundingClientRect().top;
 if(tops.indexOf(top)<0) tops.push(top);
}
return JSON.stringify({ok:true,
 headlineInView:h.inView(summary.querySelector('.summary-headline')),
 tallyInView:h.inView(summary.querySelector('.summary-tally')),
 notReachedInView:h.inView(summary.querySelector('.summary-not-reached')),
 sendInView:h.inView(send),
 sendSlack:window.innerHeight-send.getBoundingClientRect().bottom,
 notReachedSlack:window.innerHeight-summary.querySelector('.summary-not-reached').getBoundingClientRect().bottom,
 buttonRows:tops.length,buttonBottom:row.getBoundingClientRect().bottom,
 boxAfterButtons:box.previousElementSibling===row,boxTop:box.getBoundingClientRect().top,
 noHorizontalOverflow:document.documentElement.scrollWidth<=window.innerWidth,
 innerHeight:window.innerHeight,innerWidth:window.innerWidth});";
}
