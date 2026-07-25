import { getGeneratedAssetFilename } from "../helpers/filenames/asset.js";
import { getFactoryRelativeRootPath } from "../helpers/filenames/path.js";
/**
* Generate file system options
*/
function componentFactoryFileSystemOptions(base, pathPrefix) {
	const doubleDirsForCSS = base.doubleDirsForCSS ?? true;
	const prefixDirsForComponents = base.prefixDirsForComponents ?? false;
	const doubleDirsForComponents = base.doubleDirsForComponents ?? true;
	const rootPath = base.rootPath ?? getFactoryRelativeRootPath({
		doubleDirsForComponents,
		prefixDirsForComponents
	}, pathPrefix);
	return {
		doubleDirsForCSS,
		prefixDirsForComponents,
		doubleDirsForComponents,
		rootPath,
		cssPath: base.cssPath ?? getGeneratedAssetFilename("css", rootPath),
		sharedTypes: base.sharedTypes ?? false
	};
}
export { componentFactoryFileSystemOptions };
