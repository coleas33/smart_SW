using System;
using System.Net;
using System.Net.Sockets;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Loopback ports for tests that stand up an HTTP listener, without the race of asking the
/// operating system for a free port, letting it go, and binding it later.
///
/// The old pattern (a <see cref="TcpListener"/> on port 0, stopped, then the port handed to an
/// <see cref="HttpListener"/>) leaves a window in which another test or another process can take
/// the port. Under a loaded machine that window was hit: the listener's start failed within
/// milliseconds and a proxy test failed for no reason of its own. A listener here is started on
/// a fresh port and retried with a new one if the port was taken; a port that must refuse
/// connections is held by a bound socket that never listens, so nothing else can take it while
/// the test runs.
/// </summary>
internal static class LoopbackPort
{
    private const int Attempts = 50;

    /// <summary>
    /// A started <see cref="HttpListener"/> on a free loopback port, and that port. A port taken
    /// between the probe and the start is retried with a new listener on a new port.
    /// </summary>
    public static HttpListener StartListener(out int port)
    {
        HttpListenerException? last = null;
        for (int attempt = 0; attempt < Attempts; attempt++)
        {
            int candidate = ProbeFreePort();
            var listener = new HttpListener();
            listener.Prefixes.Add("http://127.0.0.1:" + candidate + "/");
            try
            {
                listener.Start();
                port = candidate;
                return listener;
            }
            catch (HttpListenerException error)
            {
                last = error;
                listener.Close();
            }
        }

        throw new InvalidOperationException(
            "no free loopback port could be listened on after " + Attempts + " attempts", last);
    }

    /// <summary>
    /// A loopback port on which a connection is refused, held for as long as the returned socket
    /// lives: the socket is bound and never listens, so a connect gets a reset and no other
    /// listener can bind the port meanwhile.
    /// </summary>
    public static Socket ReserveRefusingPort(out int port)
    {
        var socket = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp)
        {
            ExclusiveAddressUse = true,
        };
        socket.Bind(new IPEndPoint(IPAddress.Loopback, 0));
        port = ((IPEndPoint)socket.LocalEndPoint).Port;
        return socket;
    }

    private static int ProbeFreePort()
    {
        var probe = new TcpListener(IPAddress.Loopback, 0);
        probe.Start();
        try
        {
            return ((IPEndPoint)probe.LocalEndpoint).Port;
        }
        finally
        {
            probe.Stop();
        }
    }
}
