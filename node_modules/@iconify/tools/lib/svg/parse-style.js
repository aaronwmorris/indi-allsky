import { parseSVG } from "./parse.js";
import { getTokens } from "../css/parser/tokens.js";
import { parseInlineStyle } from "../css/parse.js";
import { tokensToString } from "../css/parser/export.js";
import { tokensTree } from "../css/parser/tree.js";
import { stringifyXMLContent } from "@cyberalien/svg-utils";

function assertNever(v) {}
/**
* Check callback result for Promise instance, which used to be supported in old version
*/
function assertNotOldCode(value) {
	if (value instanceof Promise) throw new Error("parseSVGStyle does not support async callbacks");
}
/**
* Parse styles in SVG
*
* This function finds CSS in SVG, parses it, calls callback for each rule.
* Callback should return new value (string) or undefined to remove rule.
*/
function parseSVGStyle(svg, callback) {
	parseSVG(svg, (item) => {
		const node = item.node;
		const tagName = node.tag;
		function parseStyleItem() {
			let content = stringifyXMLContent(node.children);
			if (!content) {
				item.removeNode = true;
				return;
			}
			content = content.replace("<![CDATA[", "").replace("]]>", "");
			const tokens = getTokens(content);
			if (!(tokens instanceof Array)) throw new Error("Error parsing style. This parser can handle only basic CSS");
			let changed = false;
			const selectorStart = [];
			let newTokens = [];
			while (tokens.length) {
				const token = tokens.shift();
				if (!token) break;
				switch (token.type) {
					case "selector":
						selectorStart.push(newTokens.length);
						newTokens.push(token);
						break;
					case "close":
						selectorStart.pop();
						newTokens.push(token);
						break;
					case "at-rule": {
						selectorStart.push(newTokens.length);
						const prop = token.rule;
						const value = token.value;
						const isAnimation = prop === "keyframes" || prop.slice(0, 1) === "-" && prop.split("-").pop() === "keyframes";
						const childTokens = [];
						const animationRules = Object.create(null);
						let depth = 1;
						let index = 0;
						let isFrom = false;
						while (depth > 0) {
							const childToken = tokens[index];
							index++;
							if (!childToken) throw new Error("Something went wrong parsing CSS");
							childTokens.push(childToken);
							switch (childToken.type) {
								case "close":
									depth--;
									isFrom = false;
									break;
								case "selector":
									depth++;
									if (isAnimation) {
										const rule = childToken.code;
										if (rule === "from" || rule === "0%") isFrom = true;
									}
									break;
								case "at-rule":
									depth++;
									if (isAnimation) throw new Error("Nested at-rule in keyframes ???");
									break;
								case "rule":
									if (isAnimation && isFrom) animationRules[childToken.prop] = childToken.value;
									break;
								default: assertNever(childToken);
							}
						}
						const skipCount = childTokens.length;
						const result = callback(isAnimation ? {
							type: "keyframes",
							prop,
							value,
							token,
							childTokens,
							from: animationRules,
							prevTokens: newTokens,
							nextTokens: tokens.slice(0)
						} : {
							type: "at-rule",
							prop,
							value,
							token,
							childTokens,
							prevTokens: newTokens,
							nextTokens: tokens.slice(0)
						});
						if (result !== void 0) {
							assertNotOldCode(result);
							if (isAnimation) {
								if (result !== value) {
									changed = true;
									token.value = result;
								}
								newTokens.push(token);
								for (let i = 0; i < skipCount; i++) tokens.shift();
								newTokens = newTokens.concat(childTokens);
							} else {
								if (result !== value) throw new Error("Changing value for at-rule is not supported");
								newTokens.push(token);
							}
						} else {
							changed = true;
							for (let i = 0; i < skipCount; i++) tokens.shift();
						}
						break;
					}
					case "rule": {
						const value = token.value;
						const selectorTokens = selectorStart.map((index) => newTokens[index]).filter((item) => item !== null);
						const result = callback({
							type: "global",
							prop: token.prop,
							value,
							token,
							selectorTokens,
							selectors: selectorTokens.reduce((prev, current) => {
								switch (current.type) {
									case "selector": return prev.concat(current.selectors);
								}
								return prev;
							}, []),
							prevTokens: newTokens,
							nextTokens: tokens.slice(0)
						});
						if (result !== void 0) {
							assertNotOldCode(result);
							if (result !== value) {
								changed = true;
								token.value = result;
							}
							newTokens.push(token);
						} else changed = true;
						break;
					}
					default: assertNever(token);
				}
			}
			if (changed) {
				const tree = tokensTree(newTokens.filter((token) => token !== null));
				if (!tree.length) item.removeNode = true;
				else node.children = [{
					type: "text",
					content: "\n" + tokensToString(tree)
				}];
			}
		}
		if (tagName === "style") {
			parseStyleItem();
			return;
		}
		const attribs = node.attribs;
		if (!attribs.style || typeof attribs.style !== "string") return;
		const parsedStyle = parseInlineStyle(attribs.style);
		if (parsedStyle === null) {
			delete attribs.style;
			return;
		}
		let changed = false;
		for (const prop in parsedStyle) {
			const value = parsedStyle[prop];
			const result = callback({
				type: "inline",
				prop,
				value,
				item
			});
			assertNotOldCode(result);
			if (result !== value) {
				changed = true;
				if (result === void 0) delete parsedStyle[prop];
				else parsedStyle[prop] = result;
			}
		}
		if (changed) {
			const newStyle = Object.keys(parsedStyle).map((key) => key + ":" + parsedStyle[key] + ";").join("");
			if (!newStyle.length) delete attribs.style;
			else attribs.style = newStyle;
		}
	});
}

export { parseSVGStyle };