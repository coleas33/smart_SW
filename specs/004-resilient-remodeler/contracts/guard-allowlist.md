# The Write Guard: stage-1 allowlist, assertions, and target verification

Two layers, because one cannot do the job. `SwGate.Call("GetChildren", () => component.GetChildren())`
guards on the **member name only**; the document is captured inside the lambda and the guard never
sees it. So "document-scoped" cannot be a property of `ICallGuard` alone. This mirrors the shape
`ReadOnlyGuard.Assert` plus `ReadOnlyGuard.AssertSaveAs` already has.

- **Layer 1**, `Guard/RemodelGuard.cs`, an `ICallGuard`: *which member may be called at all.*
- **Layer 2**, `Rms/RemodelScope.cs`: *which document it may be called on.*

## Why an allowlist here and a denylist there

`ReadOnlyGuard` is a denylist because the reviewer's **read** surface is unbounded and grows every
phase. The re-modeler is the inverse: its write surface is a closed set of about twenty members
this file enumerates. It is also exactly the workload that finds a denylist's gaps:
`ReadOnlyGuard` blocks `InsertFeatureChamfer`, `InsertFeatureShell` **and**
`InsertFeatureTreeFolder2` through its `InsertFeature` prefix, while leaving `FeatureFillet3`,
`FeatureRevolve2`, `InsertMirrorFeature2`, `InsertPart3`, `SetSuppression2` and `IModelDoc2.Save`
wide open. *Amended 2026-09-25*: the owner's decision 21A (below) closes the creation members among
them; the argument stands, because a denylist still cannot enumerate a write surface, and
`IModelDoc2.Save` is still open.

**Stage 1 adds nothing to `ReadOnlyGuard`.** The four narrowing denials
(`IFeature.SetSuppression2` exempted under `SuppressTestGuard`,
`ISldWorks.SetUserPreferenceToggle`, `IModelDoc2.EditUndo2`, `IModelDoc2.SetSaveFlag`) are feature
003's, and narrowing is not widening. The owner's decision 17A (2026-09-25) narrows it once more,
for 004: the FeatureWorks and import-repair members of the table below, and nothing is removed.
Decision 21A (the same day) narrows it again, by the creation family of the four interfaces feature
creation is reached through, and removes nothing.

### Denials added after stage 1

This file's set assertions read `ReadOnlyGuard`'s denied surface as data, so a denial another
feature adds lands here rather than in a silent drift. Recorded, so that a reader can check the
table against `RemodelGuardTests.ExpectedDeniedMembers` and against the guard itself.

**Feature 006 (the Standards check tab)** adds the members below with its cut-list and drawing
phases - the mutating and view-changing members that sit beside the reads those phases perform.
`006-standards-check/research.md` R8 is the table that fixes the membership, and therefore the
count; this list is that table's bare names, `SetText` counted once because
`ReadOnlyGuard.DeniedMemberSet` stores unqualified names.

| Members | The family they guard |
|---|---|
| `ActivateSheet`, `ActivateView` | sheet and view activation |
| `ShowExploded`, `ShowExploded2`, `CreateExplodedView`, `AutoExplode` | exploded-state writes |
| `SetVisibility`, `SetVisibilityInAsmDisplayStates`, `set_Visible` | visibility writes |
| `SetMaterialPropertyValues2`, `RemoveMaterialProperty`, `RemoveMaterialProperty2` | appearance writes |
| `set_Text`, `set_Text2` | table-cell writes |
| `AddRevision`, `DeleteRevision` | revision writes |
| `InsertRevisionTable`, `InsertRevisionTable2` | revision-table creation |
| `SetAutomaticCutList`, `UpdateCutList`, `SortCutList`, `SetAutomaticUpdate` | cut-list writes |
| `set_OverrideMass`, `SetOverrideMassValue` | mass-override writes |
| `SetOverride`, `SetText` | display-dimension writes (`SetText` also covers `INote.SetText`) |
| `SetSystemValue3`, `set_SystemValue`, `set_Value` | dimension-value writes |
| `SetName` | annotation-identity writes |
| `set_ExcludeFromCutList` | cut-list exclusion writes |

**None of them widens this allowlist.** No stage-1 key's bare name is on the list, so
`Allowlist_KeysOverridingAReadOnlyDenial_AreExactlyTheDeclaredFive` still finds the same five
(`IFeature.set_Name` and `SetName` are different names, and `ISldWorks.SetUserPreferenceToggle`
is untouched), and no member of `RemodelGuard.ExcludedMembers` became redundant. A denial is a
narrowing, so none of this is a constitution exception.

**Feature 010 (automatic mechanical checks)** adds the members below with its Hole Wizard and
`tolerance` reads (`010-mechanical-checks/contracts/tolerances.md` section 2): the setters beside
each value those reads take - the dimension tolerance, the GTol frames, the datum label, the
annotation's attachment and the Hole Wizard data. Every name was reflected on the 2024 SP5
interop (32.5.0.48); the numbered siblings of a listed setter (`SetFrameValues2`,
`SetFrameSymbols2`, `SetValues2`) are there because the same family writes the same value
through them. `set_*Diameter`, `set_*Depth` and `set_*Angle` are every such setter
`IWizardHoleFeatureData2` declares, not only the ones beside a read: `ModifyDefinition`, already
denied, is the only way a wizard edit takes effect, and these close the family by name as well.
This table is the membership: `MechanicalChecksDenylistTests` (in `GuardTests.cs`) parses it,
and `RemodelGuardTests.ExpectedDeniedMembers` lists the same bare names.

| Member (feature 010) | The read it sits beside |
|---|---|
| `IDimension.SetToleranceType`, `IDimension.SetToleranceValues`, `IDimension.SetToleranceFitValues` | `IDimension.Tolerance`; the three are the obsolete writers of the same tolerance |
| `IDimensionTolerance.set_Type`, `IDimensionTolerance.set_FitType` | `IDimensionTolerance.Type` |
| `IDimensionTolerance.SetValues`, `IDimensionTolerance.SetValues2` | `IDimensionTolerance.GetMinValue2`, `GetMaxValue2` |
| `IDimensionTolerance.SetFitValues` | `IDimensionTolerance.GetHoleFitValue`, `GetShaftFitValue` |
| `IGtol.SetFrameValues`, `IGtol.SetFrameValues2` | `IGtol.GetFrameValues` |
| `IGtol.SetFrameSymbols`, `IGtol.SetFrameSymbols2` | `IGtol.GetFrameSymbols3` |
| `IGtol.AddFrame`, `IGtol.DeleteFrame` | `IGtol.GetFrameCount`, `IGtol.GetFrame` |
| `IGtol.SetDatumIdentifier` | `IGtol.GetDatumIdentifier` |
| `IGtolFrame.SetSymbolXml`, `IGtolFrame.SetIndicator`, `IGtolFrame.AddIndicator`, `IGtolFrame.DeleteIndicator`, `IGtolFrame.SetFrameToleranceType` | `IGtolFrame.GetSymbolXml` |
| `IDatumTag.SetLabel` | `IDatumTag.GetLabel` |
| `IAnnotation.SetAttachedEntities`, `IAnnotation.ISetAttachedEntities` | `IAnnotation.GetAttachedEntities3` |
| `IWizardHoleFeatureData2.set_HoleFit` | `IWizardHoleFeatureData2.HoleFit` |
| `IWizardHoleFeatureData2.set_ThreadClass` | `IWizardHoleFeatureData2.ThreadClass` |
| `IWizardHoleFeatureData2.set_HeadClearance` | `IWizardHoleFeatureData2.HeadClearance` |
| `IWizardHoleFeatureData2.set_Diameter`, `.set_CounterBoreDiameter`, `.set_CounterDrillDiameter`, `.set_CounterSinkDiameter`, `.set_MinorDiameter`, `.set_MajorDiameter`, `.set_HoleDiameter`, `.set_ThruHoleDiameter`, `.set_TapDrillDiameter`, `.set_ThruTapDrillDiameter`, `.set_NearCounterSinkDiameter`, `.set_MidCounterSinkDiameter`, `.set_FarCounterSinkDiameter`, `.set_ThreadDiameter` | the diameter reads (`Diameter`, `ThruHoleDiameter`, `TapDrillDiameter`, `CounterBoreDiameter`, `CounterSinkDiameter`) |
| `IWizardHoleFeatureData2.set_Depth`, `.set_CounterBoreDepth`, `.set_CounterDrillDepth`, `.set_HoleDepth`, `.set_ThruHoleDepth`, `.set_TapDrillDepth`, `.set_ThruTapDrillDepth`, `.set_ThreadDepth` | the depth reads (`HoleDepth`, `ThreadDepth`, `CounterBoreDepth`) |
| `IWizardHoleFeatureData2.set_CounterDrillAngle`, `.set_CounterSinkAngle`, `.set_DrillAngle`, `.set_NearCounterSinkAngle`, `.set_MidCounterSinkAngle`, `.set_FarCounterSinkAngle`, `.set_ThreadAngle` | the angle read (`CounterSinkAngle`) |

**None of them widens this allowlist either.** No stage-1 key's bare name is among them - in
particular `set_Name` and `set_Description` are not - so the five overriding keys and
`RemodelGuard.ExcludedMembers` answer exactly as before. The reads beside them stay allowed.

**Feature 011 (drawing context, read only)** refuses, before any new drawing read lands, every
writer of the 28 drawing families and the named members of the two shared families
(`011-drawing-context/contracts/guard.md`). **This section is generated, never transcribed**: it
is the output of `extractor/tools/list-writer-members.ps1` over `SolidWorks.Interop.sldworks`
32.5.0.48, read as metadata, and `Guard/ReadOnlyGuard.Drawing.cs` is generated by the same run
with `-CSharp`. `DrawingFamilyDenylistTests` (in `GuardTests.cs`) parses the table below and
`DrawingFamilyCompletenessTests` reflects the interop to prove it complete. The "Already denied"
column names members an earlier feature (or a denied prefix) refuses; they are not added twice.
633 names are new; 646 distinct names match the writer grammar on the 28 families.

| Members refused (feature 011) | Interface; already denied |
|---|---|
| `AddCenterMark`, `AddChamferDim`, `AddHoleCallout`, `AddHoleCallout2`, `AddLineStyle`, `AddOrdinateDimension`, `AddOrdinateDimension2`, `AlignHorz`, `AlignOrdinate`, `AlignVert`, `AttachAnnotation`, `AttachDimensions`, `AutoBalloon`, `AutoBalloon2`, `AutoBalloon3`, `AutoBalloon4`, `AutoBalloon5`, `AutoDimension`, `BreakLineSplineCut`, `BreakLineStraightCut`, `BreakLineZigZagCut`, `BreakView`, `ChangeComponentLayer`, `ChangeOrdDir`, `ChangeRefConfigurationOfFlatPatternView`, `Create1stAngleViews`, `Create1stAngleViews2`, `Create3rdAngleViews`, `Create3rdAngleViews2`, `CreateAngDim`, `CreateAngDim2`, `CreateAngDim3`, `CreateAngDim4`, `CreateAutoBalloonOptions`, `CreateAuxiliaryView`, `CreateAuxiliaryViewAt`, `CreateAuxiliaryViewAt2`, `CreateBlockDefinition`, `CreateBreakOutSection`, `CreateCompoundNote`, `CreateConstructionGeometry`, `CreateCustomSymbol`, `CreateDetailView`, `CreateDetailViewAt`, `CreateDetailViewAt2`, `CreateDetailViewAt3`, `CreateDetailViewAt4`, `CreateDiamDim`, `CreateDiamDim2`, `CreateDiamDim3`, `CreateDiamDim4`, `CreateDrawViewFromModelView`, `CreateDrawViewFromModelView2`, `CreateDrawViewFromModelView3`, `CreateFlatPatternViewFromModelView`, `CreateFlatPatternViewFromModelView2`, `CreateFlatPatternViewFromModelView3`, `CreateLayer`, `CreateLayer2`, `CreateLinearDim`, `CreateLinearDim2`, `CreateLinearDim3`, `CreateLinearDim4`, `CreateOrdinateDim`, `CreateOrdinateDim2`, `CreateOrdinateDim3`, `CreateOrdinateDim4`, `CreateRelativeView`, `CreateSectionView`, `CreateSectionViewAt`, `CreateSectionViewAt2`, `CreateSectionViewAt3`, `CreateSectionViewAt4`, `CreateSectionViewAt5`, `CreateText`, `CreateText2`, `CreateUnfoldedViewAt`, `CreateUnfoldedViewAt2`, `CreateUnfoldedViewAt3`, `CreateViewport`, `CreateViewport2`, `CreateViewport3`, `DeleteAllCosmeticThreads`, `DeleteLineStyle`, `Dimensions`, `DragModelDimension`, `EditCenterMarkProperties`, `EditOrdinate`, `EditRebuild`, `EditSelectedGtol`, `EditSheet`, `EditSheet2`, `EditSketch`, `EditTemplate`, `ExplodeBlockInstance`, `ExplodeCustomSymbol`, `FlipSectionLine`, `ForceRebuild`, `HideEdge`, `HideShowDimensions`, `HideShowDrawingViews`, `IAddChamferDim`, `IAddHoleCallout2`, `ICreateAngDim`, `ICreateAngDim2`, `ICreateAngDim3`, `ICreateAngDim4`, `ICreateAuxiliaryViewAt2`, `ICreateBlockDefinition`, `ICreateCompoundNote`, `ICreateCustomSymbol`, `ICreateDetailViewAt3`, `ICreateDiamDim`, `ICreateDiamDim2`, `ICreateDiamDim3`, `ICreateDiamDim4`, `ICreateLinearDim`, `ICreateLinearDim2`, `ICreateLinearDim3`, `ICreateLinearDim4`, `ICreateOrdinateDim`, `ICreateOrdinateDim2`, `ICreateOrdinateDim3`, `ICreateOrdinateDim4`, `ICreateSectionViewAt2`, `ICreateSectionViewAt3`, `ICreateSectionViewAt4`, `ICreateSectionViewAt5`, `ICreateText2`, `IInsertCustomSymbol2`, `IInsertDowelSymbol`, `IInsertMultiJogLeader2`, `IInsertMultiJogLeader3`, `IInsertRevisionCloud`, `InsertAngularRunningDim`, `InsertBaseDim`, `InsertBlock`, `InsertBreakHorizontal`, `InsertBreakVertical`, `InsertCenterLine`, `InsertCenterLine2`, `InsertCenterMark`, `InsertCenterMark2`, `InsertCenterMark3`, `InsertChainDim`, `InsertCircularNotePattern`, `InsertCustomSymbol`, `InsertCustomSymbol2`, `InsertDatumTag`, `InsertDowelSymbol`, `InsertGroup`, `InsertHorizontalOrdinate`, `InsertLinearNotePattern`, `InsertModelAnnotations`, `InsertModelAnnotations2`, `InsertModelAnnotations3`, `InsertModelAnnotations4`, `InsertModelDimensions`, `InsertModelInPredefinedView`, `InsertMultiJogLeader`, `InsertMultiJogLeader2`, `InsertMultiJogLeader3`, `InsertNewNote`, `InsertNewNote2`, `InsertOrdinate`, `InsertRefDim`, `InsertRevisionCloud`, `InsertRevisionSymbol`, `InsertSurfaceFinishSymbol`, `InsertTableAnnotation`, `InsertTableAnnotation2`, `InsertThreadCallout`, `InsertVerticalOrdinate`, `InsertWeldSymbol`, `LoadLineStyles`, `MakeBlockDefinition`, `MakeCustomSymbol`, `MakeCustomSymbol2`, `MakeSectionLine`, `ModifySurfaceFinishSymbol`, `NewGtol`, `NewNote`, `NewSheet`, `NewSheet2`, `NewSheet3`, `NewSheet4`, `PasteSheet`, `ReorderSheets`, `ReplaceViewModel`, `ResolveOutOfDateLightWeightComponents`, `RestoreRotation`, `SaveBlock`, `SaveCustomSymbol`, `SaveLineStyles`, `SetCurrentLayer`, `SetLineColor`, `SetLineStyle`, `SetLineWidth`, `SetLineWidthCustom`, `SetSheetsSelected`, `SetupSheet`, `SetupSheet2`, `SetupSheet3`, `SetupSheet4`, `SetupSheet5`, `SetupSheet6`, `ShowEdge`, `SuppressView`, `ToggleGrid`, `UnsuppressView`, `set_AutomaticViewUpdate`, `set_BackgroundProcessingOption`, `set_HiddenViewsVisible` | `IDrawingDoc`; already denied: `ActivateSheet`, `ActivateView` |
| `CreateOLEObject`, `ICreateOLEObject`, `InsertMagneticLine`, `InsertTitleBlock`, `ReloadTemplate`, `SaveFormat`, `SetAsTableAnchor`, `SetProperties`, `SetProperties2`, `SetScale`, `SetSheetFormatName`, `SetSize`, `SetTemplateName`, `SetZoneMargin`, `SetZoneSizeDistribution`, `SetZoneSizeRegion`, `set_CustomPropertyView`, `set_FocusLocked`, `set_SheetFormatVisible` | `ISheet`; already denied: `InsertRevisionTable`, `InsertRevisionTable2`, `SetName` |
| `AlignDrawingView`, `AlignHorizontalTo`, `AlignVerticalTo`, `AlignWithView`, `AutoInsertCenterMarks`, `AutoInsertCenterMarks2`, `CreateViewArrow`, `Crop`, `Crop2`, `IInsertBomTable`, `ISetBodies`, `ISetHiddenEdges`, `ISetXform`, `InsertAlternateView`, `InsertBendTable`, `InsertBomTable`, `InsertBomTable2`, `InsertBomTable3`, `InsertBomTable4`, `InsertBomTable5`, `InsertBreak`, `InsertBreak2`, `InsertBreak3`, `InsertCutListPropertyNote`, `InsertHoleTable`, `InsertHoleTable2`, `InsertHoleTable3`, `InsertPunchTable`, `InsertViewAsBlock`, `InsertWeldTable`, `InsertWeldmentTable`, `LoadModel`, `MergeBendTags`, `ModifyViewArrow`, `MoveViewArrow`, `RemoveAlignment`, `ReplaceViewWithBlock`, `ReplaceViewWithSketch`, `ResetSketchVisibility`, `SelectEntity`, `SetBendNoteTextFormat`, `SetDisplayMode`, `SetDisplayMode2`, `SetDisplayMode3`, `SetDisplayMode4`, `SetDisplayTangentEdges`, `SetDisplayTangentEdges2`, `SetKeepLinkedToBOM`, `SetLightweightToResolved`, `SetMirrorViewOrientation`, `SetName2`, `SetResolvedToLightweight`, `SetVisible`, `SetXform`, `ShowModelBreakState`, `UpdateViewDisplayGeometry`, `set_Angle`, `set_Bodies`, `set_BreakLineGap`, `set_CropViewJaggedOutline`, `set_CropViewJaggedShapeIntensity`, `set_CropViewNoOutline`, `set_DisableAutoUpdate`, `set_DisplayState`, `set_EmphasizeOutline`, `set_FlipView`, `set_FocusLocked`, `set_HiddenEdges`, `set_IPosition`, `set_IScaleRatio`, `set_LinkParentConfiguration`, `set_ModelToViewTransform`, `set_Position`, `set_PositionLocked`, `set_ProjectedDimensions`, `set_ReferencedConfiguration`, `set_ScaleDecimal`, `set_ScaleHatchPattern`, `set_ScaleRatio`, `set_ShowSheetMetalBendNotes`, `set_SuppressState`, `set_UseParentScale`, `set_UseSheetScale` | `IView`; already denied: `ShowExploded` |
| `AddDisplayEnt`, `AddDisplayText`, `AlignToEdge`, `AutoJogOrdinate`, `IAddDisplayEnt`, `IAddDisplayText`, `ISetTextFormat`, `ResetExtensionLineStyle`, `SetArcLengthLeader`, `SetArrowHeadStyle`, `SetArrowHeadStyle2`, `SetBentLeaderLength`, `SetBrokenLeader2`, `SetDual`, `SetDual2`, `SetExtensionLineAsCenterline`, `SetHorizontal`, `SetJogParameters`, `SetLineFontDimensionStyle`, `SetLineFontDimensionThickness`, `SetLineFontExtensionStyle`, `SetLineFontExtensionThickness`, `SetLinkedText`, `SetLowerText`, `SetOrdinateDimensionArrowSize`, `SetPrecision`, `SetPrecision2`, `SetPrecision3`, `SetSecondArrow`, `SetTextFormat`, `SetUnits`, `SetUnits2`, `SetVertical`, `SetWitnessLineGap`, `Unlink`, `set_ArcExtensionLineOrOppositeSide`, `set_ArrowSide`, `set_BrokenLeader`, `set_CenterText`, `set_ChamferPrecision`, `set_ChamferTextStyle`, `set_Diametric`, `set_DimensionToInside`, `set_DisplayAsChain`, `set_DisplayAsLinear`, `set_Elevation`, `set_EndSymbol`, `set_ExtensionLineExtendsFromCenterOfSet`, `set_ExtensionLineSameAsLeaderStyle`, `set_ExtensionLineUseDocumentDisplay`, `set_Foreshortened`, `set_GridBubble`, `set_HorizontalJustification`, `set_Inspection`, `set_Jogged`, `set_LeaderVisibility`, `set_LowerInspection`, `set_MarkedForDrawing`, `set_MaxWitnessLineLength`, `set_OffsetText`, `set_RunBidirectionally`, `set_Scale2`, `set_ShortenedRadius`, `set_ShowDimensionValue`, `set_ShowLowerParenthesis`, `set_ShowParenthesis`, `set_ShowTolParenthesis`, `set_SmartWitness`, `set_SolidLeader`, `set_Split`, `set_VerticalJustification`, `set_WitnessVisibility` | `IDisplayDimension`; already denied: `SetOverride`, `SetText` |
| `ISetReferencePoints`, `ISetSystemValue3`, `ISetUserValueIn`, `ISetUserValueIn2`, `ISetUserValueIn3`, `ISetValue3`, `SetArcEndCondition`, `SetToleranceFontInfo`, `SetUserValueIn`, `SetUserValueIn2`, `SetValue2`, `SetValue3`, `set_DimensionLineDirection`, `set_DrivenState`, `set_ExtensionLineDirection`, `set_ReadOnly`, `set_ReferencePoints` | `IDimension`; already denied: `SetSystemValue2`, `SetSystemValue3`, `SetToleranceFitValues`, `SetToleranceType`, `SetToleranceValues`, `set_SystemValue`, `set_Value` |
| `SetFitFont`, `SetFont`, `set_FitDisplayStyle`, `set_ShowParenthesis` | `IDimensionTolerance`; already denied: `SetFitValues`, `SetValues`, `SetValues2`, `set_FitType`, `set_Type` |
| `AddOrUpdateStyle`, `ApplyDefaultStyleAttributes`, `ConvertToMultiJog`, `DeleteStyle`, `ISetTextFormat`, `LoadStyle`, `SaveStyle`, `Select`, `Select3`, `SelectByMark`, `SetArrowHeadSizeAtIndex`, `SetArrowHeadStyleAtIndex`, `SetLeader`, `SetLeader2`, `SetLeader3`, `SetLeaderAttachmentPointAtIndex`, `SetPosition`, `SetPosition2`, `SetStyleName`, `SetTextFormat`, `set_BentLeaderLength`, `set_Color`, `set_FrameLineStyle`, `set_FrameThickness`, `set_FrameThicknessCustom`, `set_Layer`, `set_LayerOverride`, `set_LeaderLineStyle`, `set_LeaderThickness`, `set_LeaderThicknessCustom`, `set_Owner`, `set_OwnerType`, `set_Style`, `set_UseDocDispFrame`, `set_UseDocDispLeader`, `set_Width` | `IAnnotation`; already denied: `ISetAttachedEntities`, `SetAttachedEntities`, `SetName`, `set_Visible` |
| `AddText`, `ISetTextFormat`, `ISetTextFormatAtIndex`, `MakeStackedBalloon`, `SetBalloon`, `SetBalloonPadding`, `SetBomBalloonText`, `SetHeight`, `SetHeightInPoints`, `SetHyperlinkText`, `SetTextAtIndex`, `SetTextFormat`, `SetTextFormatAtIndex`, `SetTextJustification`, `SetTextJustificationAtIndex`, `SetTextOffsetAtIndex`, `SetTextPoint`, `SetTextVerticalJustification`, `SetZeroLengthLeader`, `set_AllUpperCase`, `set_Angle`, `set_BehindSheet`, `set_IncludeDimPrefixSuffixTolerance`, `set_LockPosition`, `set_PromptText`, `set_PropertyLinkedText`, `set_ReadOnly`, `set_TagName`, `set_TextRightToLeft`, `set_ToBoundingBox`, `set_WatermarkBehindGeometry`, `set_WatermarkNote`, `set_WatermarkTransparencyLevel` | `INote`; already denied: `SetName`, `SetText`, `set_Visible` |
| `ConvertFormat`, `DeleteBelowFrameTextAt`, `ISetTextFormat`, `InsertBelowFrameTextAt`, `SetAllAroundThisSide`, `SetAllOverThisSide`, `SetBelowFrameTextAt`, `SetBetweenTwoPoints`, `SetCompositeFrame`, `SetCompositeFrame2`, `SetDisplayDualDimensionInRangeValues`, `SetFromToText`, `SetLeader`, `SetPTZHeight`, `SetPTZHeight2`, `SetPosition`, `SetTextFormat`, `set_Angle`, `set_SeparateRequirement` | `IGtol`; already denied: `AddFrame`, `DeleteFrame`, `SetDatumIdentifier`, `SetFrameSymbols`, `SetFrameSymbols2`, `SetFrameValues`, `SetFrameValues2`, `SetText` |
| `SetDisplayStyle`, `set_FilledTriangle`, `set_LeaderOrientation`, `set_Shoulder` | `IDatumTag`; already denied: `SetLabel`, `SetText` |
| `SetAngle`, `SetDirectionOfLay`, `SetSymbol`, `SetSymbolType`, `set_GOSTDefaultSymbol`, `set_GOSTNotation`, `set_Grinding`, `set_Orientation`, `set_Rotated` | `ISFSymbol`; already denied: `SetText` |
| `DeleteColumn`, `DeleteColumn2`, `DeleteRow`, `DeleteRow2`, `InsertColumn`, `InsertColumn2`, `InsertRow`, `Merge`, `MergeCells`, `MoveColumn`, `MoveRow`, `SaveAsPDF`, `SaveAsTemplate`, `SaveAsText`, `SaveAsText2`, `SetCellEquation`, `SetCellRange`, `SetCellTextFormat`, `SetCellTextOrientation`, `SetColumnTitle`, `SetColumnTitle2`, `SetColumnType`, `SetColumnType2`, `SetColumnType3`, `SetColumnWidth`, `SetHeader`, `SetLockColumnWidth`, `SetLockRowHeight`, `SetRowHeight`, `SetRowVerticalGap`, `SetTextFormat`, `Split`, `set_AnchorType`, `set_Anchored`, `set_BorderLineWeight`, `set_BorderLineWeightCustom`, `set_CellTextHorizontalJustification`, `set_CellTextVerticalJustification`, `set_ColumnHidden`, `set_GridLineWeight`, `set_GridLineWeightCustom`, `set_RowHidden`, `set_StopAutoSplitting`, `set_TextHorizontalJustification`, `set_TextVerticalJustification`, `set_Title`, `set_TitleVisible`, `set_UpperCase` | `ITableAnnotation`; already denied: `set_Text`, `set_Text2` |
| `ApplySavedSortScheme`, `Collapse`, `Dissolve`, `Expand`, `RestoreRestructuredComponents`, `SaveAsExcel`, `SetColumnCustomProperty`, `SetColumnUseTitleAsPartNumber`, `Sort` | `IBomTableAnnotation`; already denied: - |
| `ISetConfigurations`, `SetConfigurations`, `set_Configuration`, `set_DetailedCutList`, `set_DisplayAsOneItem`, `set_DissolvePartLevelRows`, `set_FollowAssemblyOrder2`, `set_KeepCurrentItemNumbers`, `set_KeepMissingItems`, `set_KeepReplacedCompOption`, `set_NumberingTypeOnIndentedBOM`, `set_PartConfigurationGrouping`, `set_RoutingComponentGrouping`, `set_SequenceStartNumber`, `set_StrikeoutMissingItems`, `set_TableType`, `set_ZeroQuantityDisplay` | `IBomFeature`; already denied: - |
| `SetColumnCustomProperty` | `IRevisionTableAnnotation`; already denied: `AddRevision`, `DeleteRevision` |
| `SetExtents` | `ITitleBlock`; already denied: - |
| `SetDatumReferenceLabel`, `SetDatumTargetHorizontal`, `SetDatumTargetNotMoveable`, `SetDatumTargetRotational`, `SetDisplay`, `SetTargetArea` | `IDatumTargetSym`; already denied: - |
| `AddToCenterMarkGroup`, `Select`, `SetExtendedLength`, `set_CenterLineFont`, `set_ConnectionLines`, `set_Gap`, `set_RotationAngle`, `set_ShowLines`, `set_Size`, `set_UseDocDisplaySettings` | `ICenterMark`; already denied: - |
| `SetFieldWeld`, `SetPeripheral`, `SetProcess`, `SetStagger`, `SetSymmetric` | `IWeldSymbol`; already denied: `SetText` |
| `set_Flipped` | `IDowelSymbol`; already denied: - |
| `set_FitDisplayStyle`, `set_FitTextHeight`, `set_FitTextScale`, `set_FitUseTextScale`, `set_ShaftFit`, `set_ShowParenthesis`, `set_TextHeight`, `set_TextScale`, `set_ToleranceMax`, `set_ToleranceMin`, `set_ToleranceType`, `set_UseTextScale` | `ICalloutVariable`; already denied: `set_FitType`, `set_HoleFit` |
| `set_Precision`, `set_TolerancePrecision` | `ICalloutLengthVariable`; already denied: - |
| `ActivateDoc`, `ActivateDoc2`, `ActivateDoc3`, `CloseAllDocuments`, `CloseAndReopen`, `CloseAndReopen2`, `DocumentVisible`, `LoadFile2`, `LoadFile3`, `LoadFile4`, `NewAssembly`, `NewDrawing`, `NewDrawing2`, `NewPart`, `OpenDoc`, `OpenDoc2`, `OpenDoc3`, `OpenDoc4`, `OpenDocSilent`, `OpenModelConfiguration`, `QuitDoc`, `RunAttachedMacro`, `RunCommand`, `RunJournalCmd`, `RunMacro`, `RunMacro2` | `ISldWorks`; already denied: - |
| `SetUserPreferenceDouble`, `SetUserPreferenceInteger`, `SetUserPreferenceString`, `SetUserPreferenceTextFormat` | `IModelDocExtension`; already denied: - |

Interfaces of the 28 whose every writer was already denied: `IGtolFrame` (`AddIndicator`, `DeleteIndicator`, `SetFrameToleranceType`, `SetIndicator`, `SetSymbolXml`).
Interfaces of the 28 with no writer on this interop: `IGeneralTableFeature`, `ITitleBlockTableFeature`, `IMultiJogLeader`, `ICalloutAngleVariable`, `ICalloutStringVariable`.

| Not denied (feature 011) | Why |
|---|---|
| `NewDocument` | `probe remodel`'s throwaway part (feature 004 T032, under `RemodelProbeGuard`, which exempts only the members `ReadOnlyGuard` refused when it was written); found by the read audit (T003) |
| `OpenDoc7` | feature 004's open of the re-modeler's own copy (`remodel.open`, a bare read call site under `RemodelGuard`) and `probe remodel`'s reopen of its throwaway part; found by the read audit (T003) |
| `Select2` | the bare name of feature 004's stage-1 allowlist key `IFeature.Select2`; denying it would make that key override a read-only denial and move `Allowlist_KeysOverridingAReadOnlyDenial_AreExactlyTheDeclaredFive` |
| `set_Name` | the bare name of feature 004's stage-1 allowlist key `IFeature.set_Name`; denying it would make that key override a read-only denial and move `Allowlist_KeysOverridingAReadOnlyDenial_AreExactlyTheDeclaredFive` |

**None of them widens this allowlist either.** No new name is the bare name of a stage-1 key or a
member `RemodelGuard` refuses itself (the "Not denied" table says which names were left allowed and
why), so the five overriding keys and `RemodelGuard.ExcludedMembers` answer exactly as before, and
the reads beside them stay allowed (`DrawingFamilyReadAuditTests`).

**Decision 17A (feature 004, 2026-09-25): FeatureWorks and import repair.** The denylist let the
members that recognize features on an imported body and build them into the part, and the
writers that repair an imported body, through a read-only gate as bare names:
`RecognizeFeatureAutomatic`, `CreateFeatures` and `ImportDiagnosis` all passed. They are refused
now, bare or interface-qualified, by `ReadOnlyGuard` and therefore by every gate built on it. Every
name was reflected on the 2024 SP5 interop (`SolidWorks.Interop.sldworks` and
`SolidWorks.Interop.fworks` 32.5.0.48, metadata only). The product calls none of them - no
string literal of the product source is one, which `ImportRepairDenylistTests` checks with the
scan `DrawingFamilyReadAuditTests` runs - and no gate's exemption names one: not the suppress-test
gate's two, not `RemodelProbeGuard`'s throwaway-part recipe (`FeatureExtrusion3`, `FeatureCut4`,
`InsertFeatureChamfer`, `InsertFeatureShell`, `InsertFeatureTreeFolder2`, `ForceRebuild3`, `SaveAs3`,
`SetSuppression2` and the two toggles, and since decision 21A `FeatureFillet3`, `InsertSketch` and
`CreateCircleByRadius`), not the twenty stage-1 keys, not `DrawingOpenGuard`'s. This
table is the membership: `ImportRepairDenylistTests` (in `GuardTests.cs`) parses it,
`RemodelGuardTests.ExpectedDeniedMembers` reads it from there, and where the interop is installed
every member is checked to exist on the interface named and every method of `IFeatureWorksApp` is
checked to be on this table or the next.

| Member (decision 17A) | What it writes |
|---|---|
| `IFeatureWorksApp.RecognizeFeatureAutomatic` | recognizes features on an imported body and builds them into the part's tree |
| `IFeatureWorksApp.RecognizeFeatureInteractive` | the same, one feature type at a time |
| `IFeatureWorksApp.CreateFeatures` | builds the recognized features into the part's tree |
| `IFeatureWorksApp.SetAdvancedOptions`, `IFeatureWorksApp.SetPerformanceOptions` | the add-in's recognition options, a setting that outlives the session |
| `IPartDoc.ImportDiagnosis` | Import Diagnostics: closes gaps and removes or repairs the faces of an imported body in place |
| `IPartDoc.ImportDiagnosisGapCloser` | moves a gap's vertices on an imported body |
| `IHealEdgesFeatureData.HealEdges` | heals the short edges of an imported body's faces |
| `IPartDoc.InsertImportedFeature` | inserts a file as an imported body feature; the `InsertFeature` prefix does not reach it |
| `IFeature.SetImportedFeatureParameters` | rewrites an imported feature's parameters |
| `IFeature.SetImportedFileName` | relinks an imported feature to another file |

Left open deliberately, each with its reason:

| Left open (decision 17A) | Why |
|---|---|
| `IFeatureWorksApp.BubbleTipCallback`, `IFeatureWorksApp.HelpErrCallback` | FeatureWorks' tooltip and help callbacks: they show help and write nothing to a document or a setting |
| `IBody2.Diagnose` | a check that returns the gaps it found as a `DiagnoseResult`, whose members are all reads |
| `ISimpleFilletFeatureData2.RepairMissingReferences` | a feature-data edit that takes effect only through `ModifyDefinition`, which is denied; a fillet repair, not an import repair |
| `IDocumentSpecification.set_AutoRepair`, `IDocumentSpecification.set_CriticalDataRepair` | options of an open request, set as plain properties rather than through the gate, exactly as `Silent` and `LoadModel` are; the product sets neither |

Decision 17A also left the rest of the creation family open (`FeatureFillet*`, `FeatureRevolve*`,
`InsertMirrorFeature*`, `InsertPart*`, `MirrorPart*` and the like), as an owner decision: a complete
denial needed a table generated from the interop as feature 011's was, not a hand list, and closing
`FeatureFillet*` needed a `RemodelProbeGuard` exemption for the throwaway part's fillet. *Closed
2026-09-25 by the owner's decision 21A, below*; until then its row stood in the table above.

**None of them widens this allowlist either.** No member of the table is the bare name of a
stage-1 key or of `RemodelGuard.ExcludedMembers`, so the five overriding keys answer as before, and
the reads beside them (`GetImportedFileName`, `GetImportedFeatureParameters`, `GetImportFileData`,
`Diagnose`, `GetGapsCount`) stay allowed. A denial is a narrowing, so none of this is a
constitution exception.

**Decision 21A (feature 004, 2026-09-25, the owner): the creation family.** `ReadOnlyGuard` refused
feature creation only through three prefixes (`FeatureCut`, `FeatureExtrusion`, `InsertFeature`),
so `FeatureFillet3`, `FeatureRevolve2`, `InsertMirrorFeature2`, `InsertPart3`, `MirrorPart2`,
`InsertSheetMetalBaseFlange2`, `InsertConvertToSheetMetal2`, the pattern creators
(`FeatureLinearPattern5`, `FeatureCircularPattern5`, `InsertTableDrivenPattern2` and the rest),
`CreateFeatureFromBody3`, `InsertRefPlane` and the hole builders all passed a read-only gate as bare
names. They are refused now, bare or interface-qualified, by `ReadOnlyGuard` and therefore by every
gate built on it, with one exemption: `RemodelProbeGuard`, for the members the throwaway part is
built with, and nothing else (below).

As feature 011's was, this table is **generated from the interop, never typed**.
`extractor/tools/list-creation-members.ps1` reflects `SolidWorks.Interop.sldworks` 32.5.0.48 as
metadata (no interop code runs and SOLIDWORKS is never started), applies the three rules below to
the four interfaces feature creation is reached through - `IFeatureManager`, `IModelDoc2`,
`IPartDoc` and `IModelDocExtension` - and prints both the generated section below and
`Guard/ReadOnlyGuard.Creation.cs`, one `string[]` that `ReadOnlyGuard`'s static constructor merges
into the denied set as it merges the drawing block. It shares its interop loader, its reading of the
guard sources and the exclusion rules of feature 011's section 3 with `list-writer-members.ps1`
(`extractor/tools/guard-table-helpers.ps1`), and reads what is already denied from
`Guard/ReadOnlyGuard.cs` and `Guard/ReadOnlyGuard.Drawing.cs`.

1. **The creation grammar.** A public method of the four interfaces is a creation member when its
   name does not start with `get_`, `Get`, `IGet` or `Is`, and matches, ordinally:

   ```text
   ^I?(Feature|Insert|Create|Add|Mirror|Make|Sketch|SimpleHole|SimpleFeature|HoleWizard|AdvancedHole)
   ```

   The verbs are the ones these interfaces name a builder with: features (`FeatureFillet3`,
   `FeatureRevolve2`, the `Feature*Pattern*` creators), inserted features, sketches, reference
   geometry, sheet metal, weldments, mirrors, base and derived parts, imported files, annotations and
   tables (`Insert*`), features and bodies built from other data, reference planes, sketch entities
   and the data objects a builder is handed (`Create*`), dimensions, relations, configurations and
   custom information (`Add*`), mirrored parts (`Mirror*`), sections and styled curves (`Make*`), the
   obsolete `IModelDoc2` sketch surface (`Sketch*`) and the holes (`SimpleHole*`, `HoleWizard*`,
   `AdvancedHole*`, `SimpleFeatureBossExtrude`). The optional `I` is a member's COM twin
   (`IInsertMacroFeature`, `ICreateFeatureFromBody3`). The grammar is written here, in the generator
   and in `CreationFamilyCompletenessTests`, the independent check of the generator's output.
2. **Named creators the grammar does not reach**, each checked by the generator to be declared on
   its interface and to be outside the grammar: the split, trim and intersect features, begun with
   `Pre` and finished with `Post` (`PreSplitBody`, `PostSplitBody` and their siblings); the last
   calls of the multi-call builders (`FinishCornerRelief`, `FinishSMNormalCut`,
   `EndVariablePitchHelix`); the Delete Face feature (`IFeatureManager.EditDeleteFace`);
   `IFeatureManager.ConvertLoftOrSweepToNetBlend`; the move, rotate and scale body features
   (`IModelDocExtension.MoveOrCopy`, `RotateOrCopy`, `ScaleOrCopy`); `IModelDoc2.DeriveSketch`; and
   `IModelDoc2.Paste`. They are a table of their own below, each with what it builds.
3. **Exclusions, each with its reason**: the bare name of a stage-1 allowlist key and a member
   `RemodelGuard` refuses itself, as feature 011's section 3 has them; and the reads the grammar
   reaches - the lookups `FeatureById`, `FeatureByName` and `FeatureByPositionReverse` (with their
   `I` twins) and `FeatureFolderLocation`, and the factories of the mass-property and measure
   calculators, `CreateMassProperty`, `CreateMassProperty2` and `CreateMeasure`, which the property
   dump, the measure source and the re-modeler's geometry gate read through. A read is never denied:
   a denylist that fails closed on a read teaches nobody anything. What an earlier table or a denied
   prefix refuses is named in the "already denied" column and not added twice.

**The throwaway part's exemption.** `probe remodel` builds its throwaway part with creation members,
so `RemodelProbeGuard` exempts exactly the ones it calls - the recipe's box, cut, fillet, chamfer,
shell and folder, the profile sketches, and PROBE-8's cylinder - under the bare names
`SwRemodelProbeHost` gates them by, and no other. The exemption is the throwaway part's scope: the
guard is built only by `probe remodel`'s gate (`Program.RemodelProbeGate`), which refuses to run
while any document is open and addresses only the part it created with `NewDocument`.
`ThrowawayPartExemptionTests` pins the set to the probe host's own literals and asserts that every
other gate the product builds refuses each member, bare or qualified, and that `RemodelProbeGuard`
itself refuses every other member of the tables and every interface-qualified spelling of its own
exemptions.

**What decision 21A does not close.** The grammar is the creation family of the four interfaces.
Their other writers - edits, suppression and visibility writers, saves and rebuilds - are not in its
scope, and neither is creation on other interfaces (`ISketchManager`, `IAssemblyDoc`'s components
and mates, `IFeature`). Among them, `IModelDoc2.Save`, `Save2`, `SaveAs`, `SaveAs2`, `SaveAs4`,
`SaveSilent` and `SaveAsSilent`, `IModelDocExtension.SaveAs` and `SaveAs2`, `IPartDoc.SaveToFile`,
`SaveToFile2` and `SaveToFile3`, `IModelDoc2.Rebuild`, `IModelDocExtension.Rebuild` and
`EditRebuildAll`, and `IPartDoc.ForceRebuild` and `EditRebuild` pass a read-only gate as bare names;
they are recorded here for the owner, not closed. No product literal names one.

**None of them widens this allowlist either.** No member of the generated tables is the bare name
of a stage-1 key or of `RemodelGuard.ExcludedMembers` (the generator excludes both, and the "Not
denied" table names what it left allowed and why), so the five overriding keys answer as before.
Every write call site of the re-modeler was already interface-qualified, and `RemodelGuard` already
refused any qualified key off its allowlist, so no remodel write changes. A denial is a narrowing,
so none of this is a constitution exception.

004 makes exactly one **visibility-only** change to that file: `DeniedMembers` and
`DeniedPrefixes` become `public static readonly IReadOnlyCollection<string>` instead of
`private static readonly`, with no member added, removed or reworded. The tests below read the
denied surface as data, and nothing exposes `SwReview.Extractor`'s internals (the only
`InternalsVisibleTo` in the tree is `SwReview.Extractor.Console`'s, `Program.cs:25`), so without
this the set assertions cannot be written at all. Exposing a denylist for reading widens no call
surface.

## Keys are interface-qualified

Allowlist keys are `Interface.Member`. Bare names collide, and both halves of the collision are
real on 2024 SP5:

- `ICustomPropertyManager.Delete2(String)` (the session-tag delete) is refused today because
  `ReadOnlyGuard` denies the bare name `Delete2`, which was meant for `IEntity.Delete2`.
- An allowlist entry for `IEquationMgr.Add3` written as `"Add3"` would silently also permit
  `ICustomPropertyManager.Add3`.

`RemodelGuard.Assert(qualifiedKey)` returns if the qualified key is on the allowlist below; else it
delegates to `ReadOnlyGuard.Assert(BareName(qualifiedKey))`, so the read-only rules still apply
unchanged to everything off the list. Only the remodel call sites use qualified keys; the
reviewer's existing `SwGate.Call("GetChildren", ...)` sites keep bare names and are untouched.

Within the remodel family the rule is **qualified keys at write call sites, bare names at read call
sites**. The probe and the remodel handlers' own reads (`GetObjectByPersistReference3`,
`IFeature.get_Name`, `GetWhatsWrongCount`, `Get4` and the scope-signal reads) use bare names exactly
as the reviewer's read sites do, so the allowlist is consulted only where a write is attempted. This
is pinned here because the gated log records strings, and a test that has to tell a read from a
write in that log needs the key style to be a decision rather than an accident.

## The stage-1 allowlist

Exactly this list. Every member below is VERIFIED present with the signature the interop manifest
records (`interop-manifest.md`); VERIFIED never means the call behaves.

| Qualified key | Used for |
|---------------|----------|
| `IModelDocExtension.ReorderFeature` | the only move operation; `location` is `Before = 2` or `After = 3` |
| `IFeatureManager.InsertFeatureTreeFolder2` | create a folder around the current contiguous selection, `Containing = 2` |
| `IFeatureManager.EditRollback` | roll the bar to the end at open, `ToEnd = 1` |
| `IFeature.set_Name` | folder naming and duplicate-feature-name repair, and nothing else |
| `IFeature.set_Description` | the description pass |
| `IFeature.Select2` | build the contiguous selection a folder wraps |
| `IEquationMgr.Add3` | the verified equation helper's first attempt |
| `IEquationMgr.Add2` | the verified equation helper's fallback |
| `IEquationMgr.Delete` | the inverse of an add, in reverse order |
| `IEquationMgr.set_Equation` | `SetEquationVerified`'s first attempt: repair an existing global in place (FR-029, `remodel.equation` `op: "set"`) |
| `IEquationMgr.SetEquationAndConfigurationOption` | `SetEquationVerified`'s fallback for the same job |
| `IModelDoc2.ForceRebuild3` | the one rebuild call |
| `IModelDoc2.ClearSelection2` | before and after every selection-based operation |
| `IModelDoc2.Save3` | the single save, no filename, behind `AssertSaveTarget` |
| `IModelDocExtension.SelectByID2` | selection where `Select2` is not enough |
| `ICustomPropertyManager.Add3` | write the session tag |
| `ICustomPropertyManager.Delete2` | remove the session tag at close |
| `ISldWorks.SetUserPreferenceToggle` | the three user-preference toggles (10, 77, 329), restored in a `finally` |
| `ISldWorks.set_CommandInProgress` | the modal-suppression flag set for the run and restored in the same `finally` (PROBE-1). It is a property, not a `swUserPreferenceToggle_e` value, so it needs its own key |
| `ISldWorks.CloseDoc` | close the tagged copy |

**`remodel.probe_scope` adds nothing to this list.** The preflight probe that reads the scope
signals off the engineer's open source (`bridge-remodel.md`) calls read members only, every one of
which `ReadOnlyGuard` already permits, so it takes `RemodelGuard`'s delegation branch and touches
no allowlist entry. It does **not** follow that the probe's `gated=` set is empty: `SwGate.Guard`
calls `observer.Gated(interopMember)` for every member *before* the guard judges it
(`extractor/SwReview.Extractor/Sw/SwGate.cs`), so reads are recorded too, and the probe's gated set
holds roughly nine read members. One test asserts instead that the probe's `refused=` set is empty,
that its `gated=` set is a subset of a named, checked-in read-only probe surface - the members of
`bridge-remodel.md`'s `scope_signals` table plus `GetOpenDocumentByName`, `GetType`, `GetSaveFlag`
and `ListExternalFileReferencesCount2` - and that no stage-1 allowlist key appears in it. That is
the machine-checkable form of "the source is only ever read".

## Explicitly not allowlisted in stage 1

Listed so that stage 1's surface cannot silently come to include them, and so that a reader can
check the list against the code.

| Not allowlisted | Why |
|-----------------|-----|
| `IModelDoc2.EditDelete` | the one call that deletes real features on a mis-selection. **Owner decision: v1 refuses a part whose tree already carries an RMS-named folder holding the wrong members**, rather than dissolving and re-wrapping it. This removes the single highest-risk allowance from the guard entirely, at the cost of refusing some legacy parts by name |
| `IModelDoc2.SaveAs3`, `IModelDocExtension.SaveAs3` | any path at all. A silent `SaveAs` renames the open document in place, and `swSaveAsOptions_Copy` was observed opening a modal Save As dialog after the file was already written; a modal on the add-in's STA thread is a hang, not an error |
| `IModelDoc2.SetSaveFlag` | forging the dirty state defeats the source-dirty preflight |
| `IModelDoc2.EditRebuild3` | one rebuild call, one meaning |
| `IModelDoc2.EditUndo2`, `EditRedo2` | returns **void** (VERIFIED), so it cannot be verified, and it shares the engineer's UI undo stack |
| `IModelDocExtension.StartRecordingUndoObject`, `FinishRecordingUndoObject2` | a UI-undo-stack mechanism this design has decided not to rely on; an unused allowlist entry is exactly the accidental widening the allowlist exists to prevent |
| `IDimension.set_Name` | v1 addresses no dimension: the IR carries none, so the planner cannot name one, and FR-030 forbids driving one. The rename-before-equations ordering rule this member existed for is kept in research.md R3.5 for the later dimensions feature. An allowlist entry with no call path is exactly the accidental widening this list exists to prevent, which is the same reason `StartRecordingUndoObject` is excluded below |
| `IFeature.SetSuppression2`, `IPartDoc.EditSuppress`, `EditUnsuppress` | suppression is feature 003's exception under its own guard, not this one's |
| `IFeature.ModifyDefinition` | redefining a feature is stage 2 |
| `Delete2` on anything but a custom property | the interface-qualified key is the whole point |
| `IModelDoc2.SetSystemValue*`, `IModelDocExtension.SetUserPreference*` | document and user preference writes beyond the four named toggles |
| the whole `FeatureCut*`, `FeatureExtrusion*`, `FeatureRevolve*`, `FeatureFillet*`, `InsertFeature*`, `InsertMirrorFeature*`, `FeatureLinearPattern*`, `FeatureCircularPattern*`, `InsertRefPlane`, `InsertPart3`, `CreateFeatureFromBody3`, `ISketchManager.*` creation family | stage 1 creates no geometry. `IFeatureManager.InsertFeatureTreeFolder2` is the single exception and is listed above by name |

Stage 2 gets a **second additive allowlist, reviewed on its own**. Stage 1's list is never widened
to accommodate it.

## `AssertSaveTarget(path)`

Called before `IModelDoc2.Save3` even though `Save3` takes no filename, because the assertion is
what the test suite pins and what the report cites.

Refuses, each with its own test: a path outside this run's folder; a path containing `..` before
canonicalization; a path equal to the source; another run's copy; a path that is not `.SLDPRT`; a
path with no extension; a `.sldasm` or `.slddrw`. Only this run's copy path passes.

## `AssertFolderSelection()`

`GetSelectedObjectCount2(-1) == 1` **and** `((IFeature)GetSelectedObject6(1, -1)).GetTypeName2()
== "FtrFolder"` (all VERIFIED). One wrong selection under a delete removes real features, so this
is a named, tested helper and is never inlined at a call site.

**In v1 it is a refusal helper, not a precondition to a write.** `IModelDoc2.EditDelete` is not on
the allowlist, so v1 has no dissolve path and nothing calls this before a delete. It has exactly
two v1 uses:

1. It is the predicate the planner's refusal is written against. A part carrying an RMS-named
   folder whose members differ from the plan is refused with `rms_named_folder_wrong_members`
   (the one token, data-model.md section 4.2), and the
   refusal names the folder using the same "one selected object and it is a `FtrFolder`" reading.
2. It is the stated precondition any future dissolve **must** pass, so stage 2 inherits a tested
   assertion rather than writing one under time pressure beside a delete.

One test asserts `IModelDoc2.EditDelete` is absent from the stage-1 allowlist, so the helper cannot
be needed in v1 by any path.

## `VerifyTarget()`

`Rms/RemodelScope.cs` is the only object that holds the copy's `IModelDoc2`. Every write method is
`VerifyTarget()` and then `gate.Call(qualifiedKey, ...)`. `VerifyTarget` is four cheap checks on
the application thread, re-run **before every single write**:

| # | Check | Catches |
|---|-------|---------|
| 1 | `document.GetPathName()` equals the copy path this run created | a different document became the handle |
| 2 | `document.Extension.CustomPropertyManager("").Get4("SwReviewRemodelRun", ...)` equals this run's id | a different copy, or the tag stripped (PROBE-12, blocking) |
| 3 | `swApp.GetOpenDocumentByName(copyPath)` returns the **same** COM identity (`Marshal.GetIUnknownForObject`) | a close-and-reopen underneath the run |
| 4 | the copy path is a canonicalized descendant of this run's folder, with `..` resolved | a path that escapes the run folder |

Any failure throws `RemodelTargetError` naming which check failed; the run aborts with the change
log intact and the copy left on disk for inspection.

**The strongest property here is structural, not procedural.** No command exposed to the model, and
no command in the bridge protocol at all, takes a document. The scope's copy is the only target
reachable. That is stronger than validating a path the caller supplied, and it is what the
constitution's exception rests on.

## Option composition, asserted as exact integers

| Call | Required | Forbidden |
|------|----------|-----------|
| `OpenDoc7` on the copy | `Silent(1) \| LoadModel(16) = 17` | `ReadOnly(2)`, `ViewOnly(4)` |
| `Save3` | `swSaveAsOptions_Silent = 1` | `Copy(2)`, `SaveReferenced(4)`, `AvoidRebuildOnSave(8)` |
| `InsertFeatureTreeFolder2` | `swFeatureTreeFolder_Containing = 2` | every other value |
| `EditRollback` | `swMoveRollbackBarToEnd = 1` | every other value |
| `ReorderFeature` | `Before = 2` or `After = 3` | `ToEnd = 1`, `ToTop = 4`, `ToFolder = 5` |

The planner's `Move.location` set is closed at `before` and `after` for the same reason
(data-model.md section 1.3), so `test_remodel_order.py` and `RemodelGuardTests` assert the same two
values from the two ends and a `to_end` move cannot be planned in the first place.

All values VERIFIED. Each row is one unit test asserting the integer the code composes, not the
name it used.

## What the tests pin without SOLIDWORKS

- `RemodelGuard` is a pure `ICallGuard`: xUnit over the allow and deny table above, including the
  `Delete2` and `Add3` interface collisions, asserted as a **set equality** against
  `ReadOnlyGuard.DeniedMembers` union `DeniedPrefixes` (readable as data after the visibility-only
  change named above), so a denial added upstream cannot silently
  widen the remodel surface, and a member added to the allowlist without a row here fails the test.
- `AssertSaveTarget`: every refusal case above, and only this run's copy passes.
- `RemodelScope` over an `IRemodelTarget` fake: tag changed mid-run refuses; path changed refuses;
  COM identity changed refuses; run-folder escape refuses; happy path asserts the exact member
  sequence, in order.
- `ToolServiceRequestLogger.Format` already records `gated=`, and it records **reads as well as
  writes**, because `SwGate.Guard` gates every member before judging it. So the assertion is not
  "the gated set contains only allowlisted keys": a mutating remodel request also gates
  `GetObjectByPersistReference3`, `IFeature.get_Name` and `GetWhatsWrongCount`, none of which are on
  the stage-1 list. One test asserts instead that a remodel request's `refused=` set is empty and
  that every gated key on `ReadOnlyGuard`'s denied surface - every key that needed the allowlist to
  pass - is on the stage-1 allowlist:
  `gated ∩ (ReadOnlyGuard.DeniedMembers ∪ DeniedPrefixes) ⊆ stage-1 allowlist`. This is
  stronger than a claim about "write keys", which the log has no way to identify. It is the same
  SC-004 audit artifact, extended rather than replaced.
- Secret policy: the general-chat secret is refused for every `remodel.*` command; the remodel
  secret is refused for `interference`.
- The frozen interop-surface manifest and its two tests (`interop-manifest.md`).

## The confirmed drawing's read-only open (feature 011): an allowlist entry of its own

The owner's answer of 2026-09-23 to feature 011's research R5 Q2 lets the product open a candidate
drawing the engineer confirms, read-only, "through the guarded seam, with its own allowlist entry"
(`011-drawing-context/contracts/confirmed-open.md` section 3, `guard.md` section 7). This is that
entry. `Guard/DrawingOpenGuard.cs` is an `ICallGuard` in the shape of `RemodelGuard`, built only by
`Sw/DrawingOpenScope.cs`: the three keys below, matched **ordinally**; any other
interface-qualified key refused naming it; a bare name - every read - answered by `ReadOnlyGuard`,
unchanged.

| Key (feature 011, confirmed open) | Used for | Composition, asserted as integers |
|---|---|---|
| `ISldWorks.DocumentVisible` | hide drawings opened from here on, then restore | `(false, swDocDRAWING = 3)` before the open; `(true, 3)` in a `finally`, also when the open throws or answers null |
| `ISldWorks.OpenDoc6` | the one read-only open | type `3`; options exactly `ReadOnly (2) \| Silent (1) = 3`, never `ViewOnly (4)`, `RapidDraft (8)` or `LoadModel (16)`; configuration `""` |
| `ISldWorks.CloseDoc` | close what the seam opened | only when the seam opened this drawing, and only after `GetOpenDocumentByName(path)` answers the **same COM identity** the open returned; otherwise nothing is closed and the read says why |

**The close rule.** A drawing that was already open is read as it stands: no visibility call, no
open, no close. The seam never closes any other document, and never a model the drawing loaded.

**It widens neither guard.** Nothing is added to `ReadOnlyGuard` or to `RemodelGuard` (whose
stage-1 allowlist and its pinned five overriding keys are unchanged). Of the three keys only
`DocumentVisible` overrides a read-only denial (feature 011's shared `ISldWorks` row);
`OpenDoc6` and `CloseDoc` are bare names `ReadOnlyGuard` already allows (feature 011's exclusions).
`DrawingOpenGuardTests` pins the set, each refusal, the delegation and the one overriding key;
`DrawingOpenScopeTests` pins the sequence, the integers, the close rule and the gate log.

**Shipped off.** `DrawingOpenScope.SeatValidated` is false until probe D14 records at a licensed
seat that the open neither changes, saves nor locks the drawing and leaves the engineer's window
where it was (feature 011 T077); while it is false a closed drawing is refused and an already-open
one is still read.
