import { IconSet } from "../icon-set/index.js";
import { ExportTargetOptions } from "./helpers/prepare.js";
import { ExportOptionsWithCustomFiles } from "./helpers/custom-files.js";
/**
 * Options
 */
interface ExportIconPackageOptions extends ExportTargetOptions, ExportOptionsWithCustomFiles {
  package?: Record<string, unknown>;
  module?: boolean;
  typesContent?: string;
  wildcardTypesVersion?: boolean;
}
/**
 * Export icon set as single icon packages
 *
 * Was used for exporting `@iconify-icons/{prefix}` packages
 */
declare function exportIconPackage(iconSet: IconSet, options: ExportIconPackageOptions): Promise<string[]>;
export { ExportIconPackageOptions, exportIconPackage };