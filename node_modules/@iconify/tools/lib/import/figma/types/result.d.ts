import { IconSet } from "../../../icon-set/index.js";
/**
 * Result for found icons
 */
interface FigmaIconNode {
  id: string;
  name: string;
  keyword: string;
  url?: string;
  content?: string;
}
/**
 * Nodes count
 */
interface FigmaNodesCount {
  nodesCount: number;
  generatedIconsCount: number;
  downloadedIconsCount: number;
}
/**
 * Import result for icons
 */
interface FigmaNodesImportResult extends Partial<FigmaNodesCount> {
  icons: Record<string, FigmaIconNode>;
}
/**
 * Import result
 */
interface FigmaImportResult extends FigmaNodesCount {
  name: string;
  version: string;
  lastModified: string;
  iconSet: IconSet;
  missing: FigmaIconNode[];
}
export { FigmaIconNode, FigmaImportResult, FigmaNodesCount, FigmaNodesImportResult };