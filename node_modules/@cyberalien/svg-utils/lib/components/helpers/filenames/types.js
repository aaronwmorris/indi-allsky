import { getUniqueHash } from "../../../helpers/hash/unique.js";
import { getGeneratedAssetFilename } from "./asset.js";
import { getGeneratedComponentFilename } from "../../export/filename.js";
/**
* Generate component types filename based on options
*/
function getGeneratedComponentTypesFilename(icon, content, options) {
	if (options.sharedTypes) return getGeneratedAssetFilename(`types/${getUniqueHash(content, {
		context: options.context,
		css: true,
		length: 8
	})}.d.ts`, options.rootPath);
	const filename = getGeneratedComponentFilename(icon, ".d.ts", options);
	const rootPath = options.rootPath.filename;
	return {
		filename: `${rootPath ? rootPath + "/" : ""}${filename}`,
		import: `./${filename.split("/").pop()}`
	};
}
export { getGeneratedComponentTypesFilename };
