import { stringifyStylesheet } from "../css/stylesheet.js";
import { getComponentSizeValues } from "./helpers/content/size.js";
import { stringifyFactoryIconContent } from "./helpers/content/stringify.js";
import { stringifyIconViewBox } from "../svg/viewbox/value.js";
import { createFactoryImports } from "./helpers/imports/create.js";
import { generateCSSFilesForComponent } from "./helpers/css/generate.js";
import { stringifyFactoryImports } from "./helpers/imports/stringify.js";
import { factoryPropTemplate, stringifyFactoryProps } from "./helpers/props/stringify.js";
import { getGeneratedComponentTypesFilename } from "./helpers/filenames/types.js";
import { addReplaceIDsFunctionAsset } from "./helpers/functions/ids.js";
import { checkForUniqueIDs } from "./helpers/code/ids.js";
/**
* Create raw component code
*/
function createRawComponent(data, options) {
	const icon = data.icon;
	const viewBox = icon.viewBox;
	const assets = [];
	const imports = createFactoryImports();
	const codeLines = [];
	const style = generateCSSFilesForComponent(icon, imports, assets, options);
	const isEmbeddedCSS = options.cssMode === "embed";
	const props = {
		xmlns: "http://www.w3.org/2000/svg",
		...getComponentSizeValues(options, viewBox),
		viewBox: stringifyIconViewBox(viewBox)
	};
	const iconContent = {
		...icon,
		content: `<svg ${stringifyFactoryProps(props, factoryPropTemplate)}>${isEmbeddedCSS && style ? `<style>${stringifyStylesheet(style)}</style>` : ""}${icon.content}</svg>`
	};
	let stringifiedContent = stringifyFactoryIconContent(iconContent);
	if (checkForUniqueIDs(iconContent.content)) stringifiedContent = `${addReplaceIDsFunctionAsset(imports, assets, options)}(${stringifiedContent})`;
	codeLines.push(`const icon = () => ${stringifiedContent};\n`);
	codeLines.push("export default icon;\n");
	const importsCode = stringifyFactoryImports(imports);
	if (importsCode) codeLines.unshift(importsCode);
	const typesContent = `declare function icon(): string;\nexport default icon;\n`;
	assets.push({
		...getGeneratedComponentTypesFilename(data, typesContent, options),
		content: typesContent
	});
	return {
		assets,
		content: codeLines.join("\n"),
		style: isEmbeddedCSS ? void 0 : style
	};
}
export { createRawComponent };
