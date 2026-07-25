import { FactoryComponent, GeneratedComponentFile } from "../types/component.js";
/**
 * Merge exported component files into single array
 */
declare function mergeExportedComponentFiles(items: FactoryComponent[], files?: GeneratedComponentFile[]): GeneratedComponentFile[];
export { mergeExportedComponentFiles };