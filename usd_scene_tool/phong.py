"""Explicit preview approximation from validated metal/rough material plans."""


def cosine_power(roughness):
    """Bounded preview heuristic, not an equivalent PBR BRDF conversion."""
    return min(1000.0, max(2.0, 2.0 / max(0.02, min(1.0, float(roughness))) ** 2 - 2.0))


def build(plan, texture):
    import maya.cmds as cmds

    node = cmds.shadingNode("phong", asShader=True, name=plan["name"] + "_Phong")
    group = cmds.sets(
        renderable=True, noSurfaceShader=True, empty=True, name=plan["name"] + "_Phong_SG"
    )
    cmds.connectAttr(node + ".outColor", group + ".surfaceShader")
    channels = {}

    def source(role):
        item = plan["inputs"][role]
        if "texture" not in item:
            return item["value"]
        data = item["texture"]
        file = texture(data)
        channels[role] = file
        attr = (
            "outColor"
            if data["channel"] == "rgb"
            else ("outAlpha" if data["channel"] == "a" else "outColor" + data["channel"].upper())
        )
        return file + "." + attr

    def put(value, plug, color=False):
        if isinstance(value, str):
            cmds.connectAttr(value, plug)
        elif color:
            cmds.setAttr(plug, *value, type="double3")
        else:
            cmds.setAttr(plug, value)

    color = source("diffuseColor")
    put(color, node + ".color", True)
    roughness = source("roughness")
    if isinstance(roughness, str):
        limit = cmds.shadingNode("clamp", asUtility=True, name=plan["name"] + "_RoughnessRange")
        cmds.setAttr(limit + ".minR", 0.02)
        cmds.setAttr(limit + ".maxR", 1)
        put(roughness, limit + ".inputR")
        power = cmds.shadingNode(
            "multiplyDivide", asUtility=True, name=plan["name"] + "_RoughnessPower"
        )
        cmds.setAttr(power + ".operation", 3)
        cmds.setAttr(power + ".input2X", -2)
        cmds.connectAttr(limit + ".outputR", power + ".input1X")
        scale = cmds.shadingNode(
            "multDoubleLinear", asUtility=True, name=plan["name"] + "_RoughnessScale"
        )
        cmds.connectAttr(power + ".outputX", scale + ".input1")
        cmds.setAttr(scale + ".input2", 2)
        offset = cmds.shadingNode(
            "addDoubleLinear", asUtility=True, name=plan["name"] + "_RoughnessOffset"
        )
        cmds.connectAttr(scale + ".output", offset + ".input1")
        cmds.setAttr(offset + ".input2", -2)
        result = cmds.shadingNode("clamp", asUtility=True, name=plan["name"] + "_CosinePowerRange")
        cmds.setAttr(result + ".minR", 2)
        cmds.setAttr(result + ".maxR", 1000)
        cmds.connectAttr(offset + ".output", result + ".inputR")
        cmds.connectAttr(result + ".outputR", node + ".cosinePower")
    else:
        cmds.setAttr(node + ".cosinePower", cosine_power(roughness))

    metallic = source("metallic")
    if isinstance(metallic, str):
        limit = cmds.shadingNode("clamp", asUtility=True, name=plan["name"] + "_MetallicRange")
        cmds.setAttr(limit + ".minR", 0)
        cmds.setAttr(limit + ".maxR", 1)
        put(metallic, limit + ".inputR")
        metallic = limit + ".outputR"
    else:
        metallic = min(1.0, max(0.0, float(metallic)))
    inverse = cmds.shadingNode("reverse", asUtility=True, name=plan["name"] + "_MetalDiffuse")
    put(metallic, inverse + ".inputX")
    cmds.connectAttr(inverse + ".outputX", node + ".diffuse")
    ior = plan["inputs"]["ior"]["value"]
    f0 = ((ior - 1) / (ior + 1)) ** 2
    specular = cmds.shadingNode("blendColors", asUtility=True, name=plan["name"] + "_MetalSpecular")
    put(color, specular + ".color1", True)
    cmds.setAttr(specular + ".color2", f0, f0, f0, type="double3")
    put(metallic, specular + ".blender")
    cmds.connectAttr(specular + ".output", node + ".specularColor")
    reflection = cmds.shadingNode(
        "blendColors", asUtility=True, name=plan["name"] + "_MetalReflection"
    )
    cmds.setAttr(reflection + ".color1", 1, 1, 1, type="double3")
    cmds.setAttr(reflection + ".color2", f0, f0, f0, type="double3")
    put(metallic, reflection + ".blender")
    cmds.connectAttr(reflection + ".outputR", node + ".reflectivity")
    if "texture" in plan["inputs"]["normal"]:
        normal = source("normal").rsplit(".", 1)[0]
        bump = cmds.shadingNode("bump2d", asUtility=True, name=plan["name"] + "_Normal")
        cmds.setAttr(bump + ".bumpInterp", 1)
        cmds.connectAttr(normal + ".outAlpha", bump + ".bumpValue")
        cmds.connectAttr(bump + ".outNormal", node + ".normalCamera")
    return node, group, channels
