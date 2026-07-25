import { FigmaDocument, IconFigmaNode } from "./api.js";
import { FigmaIconNode, FigmaNodesImportResult } from "./result.js";
type FigmaImportParentNodeType = 'CANVAS' | 'FRAME' | 'GROUP' | 'SECTION' | 'COMPONENT_SET';
type FigmaImportIconNodeType = IconFigmaNode['type'];
/**
 * Node information passed to callback
 */
interface FigmaParentNodeData {
  id: string;
  type: FigmaImportParentNodeType;
  name: string;
}
interface FigmaImportNodeData {
  id: string;
  type: FigmaImportIconNodeType;
  name: string;
  width: number;
  height: number;
  parents: FigmaParentNodeData[];
}
/**
 * Callback to check if node needs to be checked for icons
 *
 * Used to speed up processing by eleminating pages, frames and groups that do not need processing
 */
type FigmaImportParentNodeFilter = (node: FigmaParentNodeData[], document: FigmaDocument) => boolean;
/**
 * Check if node is an icon.
 *
 * Returns icon name on success, null or undefined if not should be ignored.
 * Function can also return FigmaIconNode object, where it can put extra properties that can be used later
 */
type FigmaIconNodeWithKeyword = Partial<FigmaIconNode> & Pick<FigmaIconNode, 'keyword'>;
type FigmaImportNodeFilter = (node: FigmaImportNodeData, nodes: FigmaNodesImportResult, document: FigmaDocument) => string | FigmaIconNodeWithKeyword | null | undefined;
export { FigmaImportIconNodeType, FigmaImportNodeData, FigmaImportNodeFilter, FigmaImportParentNodeFilter, FigmaImportParentNodeType, FigmaParentNodeData };