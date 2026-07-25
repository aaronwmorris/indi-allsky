import { IconSet } from "../../../icon-set/index.js";
import { FigmaIconNode } from "./result.js";
import { FigmaImportNodeFilter, FigmaImportParentNodeFilter } from "./nodes.js";
/**
 * Options for importing SVG
 */
interface FigmaImportSVGOptions {
  includeID?: boolean;
  simplifyStroke?: boolean;
  useAbsoluteBounds?: boolean;
}
/**
 * Options
 */
interface FigmaImportCommonOptions {
  token: string;
  file: string;
  version?: string;
}
interface FigmaIfModifiedSinceOption {
  ifModifiedSince: string | Date | true;
}
interface FigmaFilesQueryOptions extends FigmaImportCommonOptions, Partial<FigmaIfModifiedSinceOption> {
  ids?: string[];
  depth?: number;
}
interface FigmaImagesQueryOptions extends FigmaImportCommonOptions {
  svgOptions?: FigmaImportSVGOptions;
}
interface FigmaGetIconNodesOptions {
  pages?: string[];
  filterParentNode?: FigmaImportParentNodeFilter;
  iconNameForNode: FigmaImportNodeFilter;
}
/**
 * Callback to call before or after importing icon
 */
type FigmaImportedIconCallback = (node: FigmaIconNode, iconSet: IconSet) => void | Promise<void>;
/**
 * Options for main import function
 */
interface FigmaImportOptions extends FigmaFilesQueryOptions, FigmaImagesQueryOptions, FigmaGetIconNodesOptions {
  prefix: string;
  cacheDir?: string;
  cacheAPITTL?: number;
  cacheSVGTTL?: number;
  beforeImportingIcon?: FigmaImportedIconCallback;
  afterImportingIcon?: FigmaImportedIconCallback;
}
export { FigmaFilesQueryOptions, FigmaGetIconNodesOptions, FigmaIfModifiedSinceOption, FigmaImagesQueryOptions, FigmaImportOptions, FigmaImportSVGOptions };