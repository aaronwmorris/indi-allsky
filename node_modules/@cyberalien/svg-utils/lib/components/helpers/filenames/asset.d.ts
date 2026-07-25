import { GeneratedAssetPath } from "../../types/options.js";
declare const defaultHelpersDirectory = "helpers";
/**
 * Generate asset filename based on options
 *
 * @param filename - Filename without path
 * @param rootPath - Root path
 * @returns Asset path
 */
declare function getGeneratedAssetFilename(filename: string, rootPath: GeneratedAssetPath): GeneratedAssetPath;
export { defaultHelpersDirectory, getGeneratedAssetFilename };