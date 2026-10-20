import unittest
from runtime.security import NS,xml
from runtime.geometry import rectangular_geometry

class ImportedRectangles(unittest.TestCase):
    def shape(self,points,extra=''):
        commands=''.join(f'<a:{"moveTo" if i==0 else "lnTo"}><a:pt x="{x}" y="{y}"/></a:{"moveTo" if i==0 else "lnTo"}>' for i,(x,y) in enumerate(points))
        return xml(f'<p:sp xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}"><p:nvSpPr><p:cNvPr id="41" name="Card"/></p:nvSpPr><p:spPr><a:custGeom><a:pathLst><a:path w="200" h="100">{commands}{extra}<a:close/></a:path></a:pathLst></a:custGeom><a:solidFill><a:srgbClr val="121212"/></a:solidFill></p:spPr></p:sp>'.encode())
    def test_crossed_inset_curved_and_multi_path_art_is_not_a_container(self):
        for points,extra in [([(0,0),(200,100),(200,0),(0,100)],''),([(10,0),(200,0),(200,100),(10,100)],''),([(0,0),(200,0),(200,100),(0,100)],'<a:arcTo wR="200" hR="100" stAng="0" swAng="5400000"/>')]:
            self.assertFalse(rectangular_geometry(self.shape(points,extra)))

if __name__=='__main__':unittest.main()
