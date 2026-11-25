# Resolve every DSP physically inside an instance of the measured native XCI.
lassign $argv checkpoint module
open_checkpoint $checkpoint
set blocks [get_cells -quiet -hierarchical -filter [format {IS_PRIMITIVE == 0 && (ORIG_REF_NAME == "%s" || REF_NAME == "%s")} $module $module]]
if {![llength $blocks]} { error "No implemented multiplier hierarchy" }
set names {}
foreach dsp [get_cells -quiet -hierarchical -filter {IS_PRIMITIVE == 1 && REF_NAME =~ DSP48*}] {
    foreach block $blocks {
        if {[string first "${block}/" $dsp] == 0} {
            lappend names $dsp
            break
        }
    }
}
if {![llength $names]} { error "No DSP hardware in the updated IP" }
set fh [open dsp-ownership.txt w]
foreach name [lsort -unique $names] {puts $fh $name}
close $fh
