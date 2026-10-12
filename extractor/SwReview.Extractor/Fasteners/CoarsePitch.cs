using System;
using System.Collections.Generic;

namespace SwReview.Extractor.Fasteners;

/// <summary>
/// The ISO 261 coarse pitch of every metric diameter to 68 mm that has one (feature 010
/// amendment 2026-10-08, owner decision 52A; contracts/fasteners.md sections 8.3 and 8.8).
/// <see cref="FastenerNameParser"/> reads it to tell a pitch from a length: one bare whole
/// number after a metric size is a pitch when it is at most the size's coarse pitch ("M8x1"),
/// and a length otherwise ("M10x35").
///
/// This is the extractor's copy of the <c>metric</c> rows of
/// <c>specs/010-mechanical-checks/contracts/coarse-pitch.json</c>, the only part of that table
/// the name grammar reads; the reviewer's copy, <c>checks/coarse_pitch.yaml</c>, holds every
/// key. Each copy is pinned to the file by a test on its own side (here
/// <c>CoarsePitchContractTests</c>), so a change to the table is one commit: the file, then
/// both copies. Transcribed from ISO 261 for the owner to check against the shop's copies
/// (research R2.26).
/// </summary>
public static class CoarsePitch
{
    /// <summary>
    /// A diameter matches a row within this many millimetres, as the reviewer's
    /// <c>SIZE_EPS_MM</c> matches it.
    /// </summary>
    private const double SizeEpsilonMm = 1e-6;

    /// <summary>Each diameter and its coarse pitch, in millimetres, ascending: the contract's rows in order.</summary>
    public static IReadOnlyList<(double SizeMm, double CoarsePitchMm)> Metric { get; } =
        new (double SizeMm, double CoarsePitchMm)[]
        {
            (1, 0.25),
            (1.1, 0.25),
            (1.2, 0.25),
            (1.4, 0.3),
            (1.6, 0.35),
            (1.8, 0.35),
            (2, 0.4),
            (2.2, 0.45),
            (2.5, 0.45),
            (3, 0.5),
            (3.5, 0.6),
            (4, 0.7),
            (4.5, 0.75),
            (5, 0.8),
            (6, 1),
            (7, 1),
            (8, 1.25),
            (9, 1.25),
            (10, 1.5),
            (11, 1.5),
            (12, 1.75),
            (14, 2),
            (16, 2),
            (18, 2.5),
            (20, 2.5),
            (22, 2.5),
            (24, 3),
            (27, 3),
            (30, 3.5),
            (33, 3.5),
            (36, 4),
            (39, 4),
            (42, 4.5),
            (45, 4.5),
            (48, 5),
            (52, 5),
            (56, 5.5),
            (60, 5.5),
            (64, 6),
            (68, 6),
        };

    /// <summary>
    /// The coarse pitch of a metric diameter in millimetres, or null for a diameter with none:
    /// a fine-only size (M25) or a size in no table (M2.3).
    /// </summary>
    public static double? CoarsePitchMm(double sizeMm)
    {
        foreach ((double rowSizeMm, double coarsePitchMm) in Metric)
        {
            if (Math.Abs(rowSizeMm - sizeMm) <= SizeEpsilonMm)
            {
                return coarsePitchMm;
            }
        }

        return null;
    }
}
