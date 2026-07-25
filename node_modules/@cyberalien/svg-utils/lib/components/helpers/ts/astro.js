import { addComponentTypes } from "./wrapper.js";
/**
* Add Astro component types
*/
const addAstroComponentTypes = addComponentTypes.bind(null, `/// <reference types="astro/astro-jsx" />

interface IconProps {
/* PROPS */
}

declare const Component: (props: astroHTML.JSX.SVGAttributes & IconProps) => astroHTML.JSX.Element

export { type IconProps };
export default Component;
`);
export { addAstroComponentTypes };
