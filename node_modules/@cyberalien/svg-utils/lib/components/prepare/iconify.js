import { convertSVGContentToCSSRules } from "../../svg-css/content.js";
import { getGeneratedAssetFilename } from "../helpers/filenames/asset.js";
import { normaliseIconifyIcon } from "../../iconify/icon/normalise.js";
/**
* Convert IconifyIcon data to FactoryIconData
*/
function convertIconifyIconToFactoryContent(icon, prefix, name, options) {
	const { body, viewBox } = normaliseIconifyIcon(icon);
	const isRaw = options.raw ?? false;
	const isLegacy = options.legacy ?? false;
	const fallbackOption = isRaw || isLegacy ? false : options?.fallback ?? true;
	const defaultFallback = typeof fallbackOption === "string" ? fallbackOption : fallbackOption ? `${prefix}:${name}` : void 0;
	return {
		prefix,
		name,
		icon: {
			...isRaw ? { content: body } : convertSVGContentToCSSRules(body, options),
			viewBox,
			defaultFallback
		}
	};
}
/**
* Create metadata assets for an icon set
*/
function getIconifyIconsetMetadataAsset(iconSet, rootPath) {
	const assets = [];
	const { prefix, info, lastModified } = iconSet;
	const metadata = {
		prefix,
		info,
		lastModified
	};
	assets.push({
		...getGeneratedAssetFilename("iconify.json", rootPath),
		content: JSON.stringify(metadata, null, "	") + "\n"
	});
	return assets;
}
export { convertIconifyIconToFactoryContent, getIconifyIconsetMetadataAsset };
