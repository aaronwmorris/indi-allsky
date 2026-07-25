import { IconSet } from "../icon-set/index.js";
import { ExportTargetOptions } from "./helpers/prepare.js";
import { ExportOptionsWithCustomFiles } from "./helpers/custom-files.js";
/**
 * Options
 */
interface ExportJSONPackageOptions extends ExportTargetOptions, ExportOptionsWithCustomFiles {
  package?: Record<string, unknown>;
  customisePackage?: (contents: Record<string, unknown>) => void;
  wildcardTypesVersion?: boolean;
}
/**
 * Export icon set as JSON package
 *
 * Used for exporting `@iconify-json/{prefix}` packages
 */
declare function exportJSONPackage(iconSet: IconSet, options: ExportJSONPackageOptions): Promise<string[]>;
export { ExportJSONPackageOptions, exportJSONPackage };