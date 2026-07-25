import { ExportTargetOptions } from "../../export/helpers/prepare.js";
import { DocumentNotModified } from "../types/modified.js";
import { DownloadSourceMixin } from "../types/sources.js";
import { GitHubAPIOptions } from "./types.js";
import { UnzipFilterCallback } from "../helpers/unzip.js";
interface IfModifiedSinceOption {
  ifModifiedSince: string | DownloadGitHubRepoResult;
}
/**
 * Options for downloadGitHubRepo()
 */
interface DownloadGitHubRepoOptions extends ExportTargetOptions, GitHubAPIOptions, Partial<IfModifiedSinceOption> {
  cleanupOldFiles?: boolean;
  cleanupOldDirectories?: boolean;
  log?: boolean;
  filter?: UnzipFilterCallback;
}
/**
 * Result
 */
interface DownloadGitHubRepoResult extends DownloadSourceMixin<'github'> {
  rootDir: string;
  contentsDir: string;
  hash: string;
}
/**
 * Download GitHub repo using API
 */
declare function downloadGitHubRepo<T extends IfModifiedSinceOption & DownloadGitHubRepoOptions>(options: T): Promise<DownloadGitHubRepoResult | DocumentNotModified>;
declare function downloadGitHubRepo(options: DownloadGitHubRepoOptions): Promise<DownloadGitHubRepoResult>;
export { DownloadGitHubRepoOptions, DownloadGitHubRepoResult, downloadGitHubRepo };