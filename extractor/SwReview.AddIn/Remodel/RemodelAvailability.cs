namespace SwReview.AddIn.Remodel;

/// <summary>
/// Whether the bridge behind the Remodel tab can reach a SOLIDWORKS remodel seat.
/// Unknown is the normal state while the tool service is attaching; it must not be
/// confused with an attached bridge that deliberately has no seat.
/// </summary>
public enum RemodelAvailability
{
    Unknown,
    Unavailable,
    Available,
}
