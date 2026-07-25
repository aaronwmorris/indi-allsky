import { IconSet } from "../icon-set/index.js";
import { ExportTargetOptions } from "./helpers/prepare.js";
/**
 * Options
 */
interface ExportToDirectoryOptions extends ExportTargetOptions {
  autoHeight?: boolean;
  includeAliases?: boolean;
  includeChars?: boolean;
  log?: boolean;
}
/**
 * Export icon set to directory
 *
 * Returns list of stored files
 */
declare function exportToDirectory(iconSet: IconSet, options: ExportToDirectoryOptions): Promise<string[]>;
export { ExportToDirectoryOptions, exportToDirectory };