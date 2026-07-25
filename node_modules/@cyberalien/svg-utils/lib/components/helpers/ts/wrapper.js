import { stringifyFactoryPropTypes } from "../props/ts.js";
import { getGeneratedComponentTypesFilename } from "../filenames/types.js";
/**
* Properties to omit
*/
const omitComponentSVGProps = `'viewBox' | 'width' | 'height' | 'xmlns'`;
/**
* Add component types
*/
function addComponentTypes(template, data, options, assets, props) {
	const propTypes = stringifyFactoryPropTypes(props);
	const content = template.replace("/* PROPS */", propTypes);
	const filename = getGeneratedComponentTypesFilename(data, content, options);
	assets.push({
		...filename,
		content
	});
	return filename.filename;
}
export { addComponentTypes, omitComponentSVGProps };
