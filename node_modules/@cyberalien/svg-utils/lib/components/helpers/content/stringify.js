import { stringifyStylesheet } from "../../../css/stylesheet.js";
/**
* Convert icon content to a string literal
*/
function stringifyFactoryIconContent(icon, embedCSS, addQuotes = true) {
	const style = embedCSS ? stringifyStylesheet(embedCSS) : "";
	const fullContent = style ? `<style>${style}</style>${icon.content}` : icon.content;
	return addQuotes ? "`" + fullContent.replace(/`/g, "\\`") + "`" : fullContent;
}
export { stringifyFactoryIconContent };
