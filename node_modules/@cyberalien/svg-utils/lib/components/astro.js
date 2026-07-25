import { stringifyStylesheet } from "../css/stylesheet.js";
import { getComponentSizeValues } from "./helpers/content/size.js";
import { stringifyFactoryIconContent } from "./helpers/content/stringify.js";
import { stringifyIconViewBox } from "../svg/viewbox/value.js";
import { createFactoryImports } from "./helpers/imports/create.js";
import { generateCSSFilesForComponent } from "./helpers/css/generate.js";
import { addSizeFunctionAsset } from "./helpers/functions/size.js";
import { stringifyFactoryImports } from "./helpers/imports/stringify.js";
import { makeSquareViewBox } from "../svg/viewbox/square.js";
import { stringifyFactoryProps } from "./helpers/props/stringify.js";
import { getUsedFactoryProps, stringifyFactoryPropTypes } from "./helpers/props/ts.js";
import { getViewBoxRatio } from "./helpers/content/ratio.js";
import { addCustomFunctionAsset } from "./helpers/functions/custom.js";
import { addAstroComponentTypes } from "./helpers/ts/astro.js";
import { addReplaceIDsFunctionAsset } from "./helpers/functions/ids.js";
import { cleanupJSXRenamedProps } from "./helpers/props/cleanup.js";
import { checkForUniqueIDs } from "./helpers/code/ids.js";
/**
* Create Astro component code
*/
function createAstroComponent(data, options) {
	const icon = data.icon;
	const viewBox = icon.viewBox;
	const statefulData = icon.statefulData;
	const assets = [];
	const imports = createFactoryImports();
	const styleContent = generateCSSFilesForComponent(icon, imports, assets, options);
	let hasFixedSize = !!options.width && !!options.height;
	const hasComputedViewbox = options.square && !hasFixedSize && viewBox.width !== viewBox.height;
	if (!hasComputedViewbox && (options.width || options.height)) hasFixedSize = true;
	const componentCode = [];
	const props = { xmlns: "http://www.w3.org/2000/svg" };
	if (statefulData) {
		const { supportedStates, allStates, staticClassname } = statefulData;
		if (supportedStates.size || staticClassname) {
			const computedStates = [];
			let addedStateFunc = false;
			for (const state of allStates) if (typeof state === "string") {
				if (supportedStates.has(state)) {
					props[state] = {
						type: "boolean",
						value: state,
						template: ""
					};
					computedStates.push(`'${state}': ${state}Prop`);
				}
			} else {
				const stateName = state[0];
				if (supportedStates.has(stateName)) {
					const stateValues = state[1];
					const defaultStateValue = state[2] ?? stateValues[0];
					props[stateName] = {
						type: stateValues.map((value) => `'${value}'`).join(" | "),
						value: stateName,
						template: ""
					};
					computedStates.push(`'${stateName}': namedStateValue(${stateName}Prop, '${defaultStateValue}')`);
					if (!addedStateFunc) {
						addedStateFunc = true;
						addCustomFunctionAsset(imports, assets, options, {
							functionName: "namedStateValue",
							content: `export function namedStateValue(value, defaultValue) {
		return value && value !== defaultValue ? value : undefined;
	}`
						});
					}
				}
			}
			if (staticClassname) {
				const state = "static";
				props[state] = {
					type: "boolean",
					value: state,
					template: ""
				};
				computedStates.push(`'${state}': ${state}Prop`);
			}
			if (computedStates.length) {
				componentCode.push(`const states = { ${computedStates.join(", ")} };`);
				componentCode.push(`const className = Object.entries(states).map(([key, value]) => value ? \`state-\${value === true ? key : value}\` : '').join(' ').trim();`);
				props.class = {
					value: "className",
					template: "class={className}"
				};
			}
		}
	}
	const viewBoxPropValue = `viewBox${hasComputedViewbox ? "Computed" : ""}`;
	const getViewBox = (viewBox) => `'${stringifyIconViewBox(viewBox)}'`;
	if (hasComputedViewbox) componentCode.push(`const baseViewBox = ${getViewBox(viewBox)};`, `const squareViewBox = ${getViewBox(makeSquareViewBox(viewBox))};`, `const ${viewBoxPropValue} = squareProp ? squareViewBox : baseViewBox;`);
	else componentCode.push(`const ${viewBoxPropValue} = ${getViewBox(viewBox)};`);
	const ratioValue = getViewBoxRatio(viewBox);
	if (hasComputedViewbox) componentCode.push(`const ratio = squareProp ? 1 : ${ratioValue};`);
	if (hasFixedSize) {
		const sizeProps = getComponentSizeValues(options, viewBox);
		if (!sizeProps) throw new Error("Fixed size expected, but could not be determined");
		props.width = sizeProps.width;
		props.height = sizeProps.height;
	} else {
		const getSizeProps = addSizeFunctionAsset(imports, assets, options);
		componentCode.push(`const size = ${getSizeProps}(widthProp, heightProp, ${hasComputedViewbox ? "ratio" : ratioValue});`);
		props.width = {
			type: "string",
			value: "width",
			template: "{...size}"
		};
		props.height = {
			type: "string",
			value: "height",
			template: ""
		};
	}
	if (options.square) props.square = { type: "boolean" };
	props.viewBox = {
		value: "viewBox",
		template: `viewBox={${viewBoxPropValue}}`
	};
	let stringifiedContent = stringifyFactoryIconContent(icon);
	if (checkForUniqueIDs(icon.content)) stringifiedContent = `${addReplaceIDsFunctionAsset(imports, assets, options)}(${stringifiedContent})`;
	componentCode.push(`const content = ${stringifiedContent};`);
	const usedProps = getUsedFactoryProps(props);
	const propsDestricturing = usedProps.length ? `{${[...usedProps.map((prop) => `${prop}: ${prop}Prop`), "...props"].join(", ")}}` : "props";
	componentCode.unshift(`const ${propsDestricturing} = Astro.props;\n`);
	const propTypes = stringifyFactoryPropTypes(props);
	if (propTypes.trim()) componentCode.unshift(`/** @type {{${propTypes.replace(/\s*\n\s*/g, " ").trim()}}} */`);
	const template = `<svg ${stringifyFactoryProps(props, "{prop}={{value}}")} {...props} set:html={content}></svg>`;
	let content = `---
${(stringifyFactoryImports(imports) + "\n" + componentCode.join("\n")).trim()}
---

${template}
`;
	const style = options.cssMode === "prop" ? styleContent : void 0;
	if (styleContent && !style) content += `<style>\n${stringifyStylesheet(styleContent)}\n</style>\n`;
	const types = addAstroComponentTypes(data, options, assets, props);
	return {
		assets,
		content: cleanupJSXRenamedProps(content),
		style,
		types
	};
}
export { createAstroComponent };
