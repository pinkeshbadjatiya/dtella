from distutils.core import setup
import py2exe
setup(
    options={"py2exe":{"optimize":2}},
	
    #windows=[{
    #    "script": "dtella.py",
    #    "icon_resources": [(1, "dcgate.ico")]
    #}]

    console=[{"script": "dtella.py"}]
)
