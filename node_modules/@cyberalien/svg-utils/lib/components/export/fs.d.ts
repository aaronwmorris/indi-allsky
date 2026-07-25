import { GeneratedComponentFile } from "../types/component.js";
/**
 * Save exported files to filesystem
 */
declare function saveExportedFilesToFS(files: GeneratedComponentFile[], dir: string): Promise<number>;
export { saveExportedFilesToFS };