import { APICacheOptions } from "../../download/api/types.js";
import { DocumentNotModified } from "../../download/types/modified.js";
import { FigmaDocument } from "./types/api.js";
import { FigmaIconNode, FigmaNodesImportResult } from "./types/result.js";
import { FigmaFilesQueryOptions, FigmaIfModifiedSinceOption, FigmaImagesQueryOptions } from "./types/options.js";
/**
 * Extra parameters added to runConcurrentQueries()
 *
 * Can be used to identify failed items in onfail callback
 */
interface FigmaIconNodeWithURL extends FigmaIconNode {
  url: string;
}
type FigmaConcurrentQueriesParamsFunction = 'figmaImagesQuery' | 'figmaDownloadImages';
interface FigmaConcurrentQueriesParams<T extends FigmaConcurrentQueriesParamsFunction> {
  function: T;
  payload: T extends 'figmaImagesQuery' ? string[][] : FigmaIconNodeWithURL[];
}
/**
 * Get Figma files
 */
declare function figmaFilesQuery<T extends FigmaIfModifiedSinceOption & FigmaFilesQueryOptions>(options: T, cache?: APICacheOptions): Promise<FigmaDocument | DocumentNotModified>;
declare function figmaFilesQuery(options: FigmaFilesQueryOptions, cache?: APICacheOptions): Promise<FigmaDocument>;
/**
 * Generate all images
 */
declare function figmaImagesQuery(options: FigmaImagesQueryOptions, nodes: FigmaNodesImportResult, cache?: APICacheOptions): Promise<FigmaNodesImportResult>;
/**
 * Download all images
 */
declare function figmaDownloadImages(nodes: FigmaNodesImportResult, cache?: APICacheOptions): Promise<FigmaNodesImportResult>;
export { FigmaConcurrentQueriesParams, FigmaConcurrentQueriesParamsFunction, figmaDownloadImages, figmaFilesQuery, figmaImagesQuery };