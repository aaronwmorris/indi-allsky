import { addComponentTypes, omitComponentSVGProps } from "./wrapper.js";
/**
* Add Solid component types
*/
const addSolidComponentTypes = addComponentTypes.bind(null, `import { JSX } from 'solid-js';

interface IconProps {
/* PROPS */
}

declare const Component: (
	props: Omit<JSX.SvgSVGAttributes<SVGSVGElement>, ${omitComponentSVGProps}> & IconProps
) => JSX.Element;

export { type IconProps };
export default Component;
`);
export { addSolidComponentTypes };
