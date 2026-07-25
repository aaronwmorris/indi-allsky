import { SVG } from "./index.js";
import { AnalyseSVGStructureOptions, AnalyseSVGStructureResult } from "./analyse/types.js";
/**
 * Find all IDs, links, which elements use palette, which items aren't used
 *
 * Before running this function run cleanup functions to change inline style to attributes and fix attributes
 */
declare function analyseSVGStructure(svg: SVG, options?: AnalyseSVGStructureOptions): AnalyseSVGStructureResult;
export { analyseSVGStructure };