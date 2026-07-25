import { parseSVG } from "../parse.js";
import { allValidTags, animateMotionChildTags, badTags, feComponentTransferChildTag, feLightningChildTags, feLightningTags, feMergeChildTags, filterChildTags, filterTag, gradientChildTags, gradientTags, unsupportedTags } from "../data/tags.js";
import { stringifyXMLContent } from "@cyberalien/svg-utils";

const requiredParentTags = /* @__PURE__ */ new Map();
requiredParentTags.set(new Set(["feComponentTransfer"]), feComponentTransferChildTag);
requiredParentTags.set(new Set(["feMerge"]), feMergeChildTags);
requiredParentTags.set(feLightningTags, feLightningChildTags);
requiredParentTags.set(filterTag, filterChildTags);
requiredParentTags.set(gradientTags, gradientChildTags);
requiredParentTags.set(new Set(["animateMotion"]), animateMotionChildTags);
const defaultOptions = { keepTitles: false };
/**
* Test for bag tags
*/
function checkBadTags(svg, options) {
	const { keepTitles } = {
		...defaultOptions,
		...options
	};
	parseSVG(svg, (item) => {
		const node = item.node;
		const tagName = node.tag;
		if (tagName === "svg") {
			if (item.parents.length) throw new Error(`Unexpected element: <${tagName}>`);
			return;
		}
		if (keepTitles && tagName === "title") {
			const content = stringifyXMLContent(node.children);
			if (content?.includes("<") || content?.includes(">")) {
				item.removeNode = true;
				item.testChildren = false;
			}
			return;
		}
		if (unsupportedTags.has(tagName)) {
			item.removeNode = true;
			item.testChildren = false;
			return;
		}
		if (badTags.has(tagName) || !allValidTags.has(tagName)) {
			if (tagName.split(":").length > 1) {
				item.removeNode = true;
				item.testChildren = false;
				return;
			}
			throw new Error(`Unexpected element: <${tagName}>`);
		}
		const parentTagName = item.parents[0]?.node.tag ?? "";
		for (const [parents, children] of requiredParentTags) if (children.has(tagName)) {
			if (!parents.has(parentTagName)) throw new Error(`Element <${tagName}> has wrong parent element`);
			return;
		}
	});
}

export { checkBadTags };