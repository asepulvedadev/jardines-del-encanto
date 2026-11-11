export type PlanMeasurement = {
  value: string;
  source: string;
  position: number[];
  edgeIndex: number | null;
};
export type MasterplanLot = {
  id: string;
  sourceLabel: string;
  blockId: string;
  areaM2: number | null;
  areaSource: string | null;
  areaLabel: string | null;
  areaPosition: number[] | null;
  measurements: PlanMeasurement[];
  path: string | null;
  bounds: number[];
  center: number[];
  geometrySource: string;
  anomalies: string[];
};
export type MasterplanBlock = {
  id: string;
  label: string;
  bounds: number[];
  path: string;
  count: number;
};
export type MasterplanData = {
  metadata: {
    sourceSha256: string;
    sourceLabelOccurrences: number;
    sourceAreaLabels: number;
    parseableAreaLabels: number;
    endpointReconciliations: number;
    resolvedGeometry: number;
    unresolvedGeometry: number;
    georeferenced: boolean;
    extraction: string;
  };
  viewBox: number[];
  blocks: MasterplanBlock[];
  lots: MasterplanLot[];
};
