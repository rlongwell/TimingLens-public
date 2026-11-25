"""Allowlisted Vivado 2024.2 / 7-series non-project implementation recipes."""
from dataclasses import dataclass, asdict
from importlib.resources import files

OPT_PLACE = 'https://docs.amd.com/r/2024.2-English/ug904-vivado-implementation/Directives-Used-by-opt_design-and-place_design-in-Implementation-Strategies'
PHYS_ROUTE = 'https://docs.amd.com/r/2024.2-English/ug904-vivado-implementation/Directives-Used-by-phys_opt_design-and-route_design-in-Implementation-Strategies'


@dataclass(frozen=True)
class Recipe:
    name: str
    opt: str
    place: str
    phys_opt: str
    route: str

    def directives(self):
        return {key:value for key,value in asdict(self).items() if key!='name'} | {'threads':'2','seed':'No seed override'}

    def commands(self):
        commands=['opt_design' if self.opt=='Default' else f'opt_design -directive {self.opt}',
                  f'place_design -directive {self.place}']
        if self.phys_opt!='not run':commands.append(f'phys_opt_design -directive {self.phys_opt}')
        return (*commands,f'route_design -directive {self.route}')


RECIPES = {
    'default':Recipe('Default','Default','Default','not run','Default'),
    'explore':Recipe('Performance_Explore','Explore','Explore','Explore','Explore'),
    'extra_timing':Recipe('Performance_ExtraTimingOpt','Default','ExtraTimingOpt','Explore','NoTimingRelaxation'),
}


def validate_recipes(strategies):
    if (not isinstance(strategies,tuple) or not strategies or strategies[0]!='default'
            or any(s not in RECIPES for s in strategies) or len(set(strategies))!=len(strategies)):
        raise ValueError('Recipes must be unique allowlisted IDs, with default first.')


def variant_name(strategy):
    if strategy not in RECIPES:raise ValueError('Unknown counter strategy.')
    return 'candidate' if strategy=='default' else 'candidate_'+strategy


def build_script(strategy):
    if strategy not in RECIPES:raise ValueError('Unknown counter strategy.')
    template=files('timinglens.experiments').joinpath('counter_build.tcl').read_text()
    original=''.join('    '+line+'\n' for line in RECIPES['default'].commands())
    if template.count(original)!=1:raise ValueError('Counter build template no longer matches its recipe insertion point.')
    return template.replace(original,''.join('    '+line+'\n' for line in RECIPES[strategy].commands()),1).encode()
