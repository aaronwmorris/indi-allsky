import { ExportTargetOptions } from "../../export/helpers/prepare.js";
import { DocumentNotModified } from "../types/modified.js";
import { DownloadSourceMixin } from "../types/sources.js";
import { NPMPackageOptions } from "./types.js";
interface IfModifiedSinceOption {
  ifModifiedSince: string | true | DownloadNPMPackageResult;
}
/**
 * Options for downloadNPMPackage()
 */
interface DownloadNPMPackageOptions extends NPMPackageOptions, ExportTargetOptions, Partial<IfModifiedSinceOption> {
  log?: boolean;
}
/**
 * Result
 */
interface DownloadNPMPackageResult extends DownloadSourceMixin<'npm'> {
  rootDir: string;
  contentsDir: string;
  version: string;
}
/**
 * Download NPM package
 */
declare function downloadNPMPackage<T extends IfModifiedSinceOption & DownloadNPMPackageOptions>(options: T): Promise<DownloadNPMPackageResult | DocumentNotModified>;
declare function downloadNPMPackage(options: DownloadNPMPackageOptions): Promise<DownloadNPMPackageResult>;
export { DownloadNPMPackageOptions, DownloadNPMPackageResult, downloadNPMPackage };