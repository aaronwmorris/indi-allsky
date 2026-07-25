import { iconToSVG, prettifySVG, trimSVG } from "@iconify/utils";
import { parseXMLContent, stringifyXMLContent } from "@cyberalien/svg-utils";
import { parseViewBox } from "@cyberalien/svg-utils/lib/svg/viewbox/parse.js";

/**
* SVG class, used to manipulate icon content.
*/
var SVG = class {
	$svg;
	viewBox;
	/**
	* Constructor
	*/
	constructor(content) {
		this.load(content);
	}
	/**
	* Get SVG as string
	*/
	toString(customisations, prettyPrint = false) {
		if (customisations) {
			const data = iconToSVG(this.getIcon(), customisations);
			let svgAttributes = " xmlns=\"http://www.w3.org/2000/svg\"";
			if (data.body.includes("xlink:")) svgAttributes += " xmlns:xlink=\"http://www.w3.org/1999/xlink\"";
			for (const key in data.attributes) {
				const value = data.attributes[key];
				svgAttributes += " " + key + "=\"" + value + "\"";
			}
			const svg = "<svg" + svgAttributes + ">" + data.body + "</svg>";
			return prettyPrint === true ? prettifySVG(svg) || svg : trimSVG(svg);
		}
		const $root = this.$svg;
		const attribs = $root.attribs;
		const box = this.viewBox;
		if (!attribs["viewBox"]) attribs["viewBox"] = `${box.left} ${box.top} ${box.width} ${box.height}`;
		for (const prop of ["width", "height"]) if (!attribs[prop]) attribs[prop] = box[prop];
		const result = stringifyXMLContent([$root], { prettyPrint });
		return prettyPrint === false ? trimSVG(result) : result;
	}
	/**
	* Get SVG as string without whitespaces
	*/
	toMinifiedString(customisations) {
		return this.toString(customisations, false);
	}
	/**
	* Get SVG as string with whitespaces
	*/
	toPrettyString(customisations) {
		return this.toString(customisations, true);
	}
	/**
	* Get body
	*/
	getBody() {
		const $root = this.$svg;
		const attribs = $root.attribs;
		for (const key in attribs) switch (key.split("-").shift()) {
			case "fill":
			case "stroke":
			case "opacity": throw new Error(`Cannot use getBody() on icon that was not cleaned up with cleanupSVGRoot(). Icon has attribute ${key}="${attribs[key]}"`);
		}
		return stringifyXMLContent($root.children);
	}
	/**
	* Get icon as IconifyIcon
	*/
	getIcon() {
		const props = this.viewBox;
		const body = this.getBody();
		return {
			...props,
			body
		};
	}
	/**
	* Load SVG
	*
	* @param {string} content
	*/
	load(content) {
		function remove(str1, str2, append) {
			let start = 0;
			while ((start = content.indexOf(str1, start)) !== -1) {
				const end = content.indexOf(str2, start + str1.length);
				if (end === -1) return;
				content = content.slice(0, start) + append + content.slice(end + str2.length);
				start = start + append.length;
			}
		}
		remove("<!--", "-->", "");
		remove("<?xml", "?>", "");
		remove("<!DOCTYPE svg", "<svg", "<svg");
		remove("xmlns:x=\"&ns_extend;\" xmlns:i=\"&ns_ai;\" xmlns:graph=\"&ns_graphs;\"", "", "");
		remove("xml:space=\"preserve\"", "", "");
		content = content.replace(/<g>\s*<\/g>/g, "");
		const root = parseXMLContent(content);
		if (!root || root.length !== 1) throw new Error("Invalid SVG file");
		const rootTag = root[0];
		if (rootTag.type !== "tag" || rootTag.tag !== "svg") throw new Error("Invalid SVG file: missing <svg> root element");
		this.$svg = rootTag;
		const attribs = rootTag.attribs;
		const viewBox = attribs["viewBox"];
		if (typeof viewBox === "string") {
			const parsed = parseViewBox(viewBox);
			if (!parsed) throw new Error("Invalid SVG file: bad viewBox attribute");
			this.viewBox = parsed;
		} else {
			let width = attribs["width"];
			let height = attribs["height"];
			if (!width || !height) throw new Error("Invalid SVG file: missing dimensions");
			if (typeof width === "string") width = parseFloat(width);
			if (typeof height === "string") height = parseFloat(height);
			const parsed = parseViewBox(`0 0 ${width} ${height}`);
			if (!parsed) throw new Error("Invalid SVG file: bad size attributes and no viewBox");
			this.viewBox = parsed;
		}
	}
};

export { SVG };