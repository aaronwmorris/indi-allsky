import { getGeneratedAssetFilename } from "../filenames/asset.js";
import { camelToKebab } from "../../../helpers/misc/strings.js";
/**
* Adds a custom function to assets
*/
function addCustomFunctionAsset(imports, assets, options, data) {
	const { functionName, content, exportNames } = data;
	const filename = getGeneratedAssetFilename(`${options.helpersDirectory ?? "helpers"}/${data.jsName ?? camelToKebab(functionName)}.js`, options.rootPath);
	assets.push({
		...filename,
		content
	});
	imports.named[filename.import] = exportNames ?? new Set([functionName]);
}
export { addCustomFunctionAsset };
