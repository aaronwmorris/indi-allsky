import { addComponentTypes } from "./wrapper.js";
/**
* Add Vue component types
*/
const addVueComponentTypes = addComponentTypes.bind(null, `import { DefineSetupFnComponent, PublicProps } from 'vue';

interface IconProps {
/* PROPS */
}

declare const Component: DefineSetupFnComponent<IconProps, {}, {}, IconProps & {}, PublicProps>;

export { type IconProps };
export default Component;
`);
export { addVueComponentTypes };
