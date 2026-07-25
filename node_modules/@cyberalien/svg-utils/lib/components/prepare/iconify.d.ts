import { FactoryIconData } from "../types/data.js";
import { GeneratedAssetPath } from "../types/options.js";
import { GeneratedAssetFile } from "../types/component.js";
import { ConvertSVGContentOptions } from "../../svg-css/types.js";
import { IconifyIcon, IconifyJSON } from "@iconify/types";
interface Options extends ConvertSVGContentOptions {
  raw?: boolean;
  fallback?: string | boolean;
}
/**
 * Convert IconifyIcon data to FactoryIconData
 */
declare function convertIconifyIconToFactoryContent(icon: IconifyIcon, prefix: string, name: string, options: Options): FactoryIconData;
/**
 * Create metadata assets for an icon set
 */
declare function getIconifyIconsetMetadataAsset(iconSet: Pick<IconifyJSON, 'prefix' | 'info' | 'lastModified'>, rootPath: GeneratedAssetPath): GeneratedAssetFile[];
export { convertIconifyIconToFactoryContent, getIconifyIconsetMetadataAsset };