const defaultHelpersDirectory = "helpers";
/**
* Generate asset filename based on options
*
* @param filename - Filename without path
* @param rootPath - Root path
* @returns Asset path
*/
function getGeneratedAssetFilename(filename, rootPath) {
	const basePath = rootPath.filename;
	return {
		import: `${rootPath.import}/${filename}`,
		filename: `${basePath ? basePath + "/" : ""}${filename}`
	};
}
export { defaultHelpersDirectory, getGeneratedAssetFilename };
