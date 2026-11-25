# Associate primitives with the closest requested original module in the native netlist.
proc resource_owners {filename} {
    set f [open $filename r]; set modules [split [string trim [read $f]] "\n"]; close $f
    set scope [dict create]
    foreach c [get_cells -quiet -hierarchical -filter {IS_PRIMITIVE == 0}] {
        foreach ref [list [get_property -quiet ORIG_REF_NAME $c] [get_property REF_NAME $c]] {
            if {$ref ne "" && $ref in $modules} {
                dict set scope $c $ref
                break
            }
        }
    }
    set top [get_property NAME [current_design]]
    if {$top in $modules} {dict set scope "" $top}
    set counts [dict create]
    foreach c [get_cells -quiet -hierarchical -filter {IS_PRIMITIVE == 1}] {
        set ref [get_property REF_NAME $c]
        switch -glob -- $ref {
            DSP48* {set kind dsp}
            RAMB18* {set kind ramb18}
            RAMB36* {set kind ramb36}
            RAM* {set kind lutram}
            LUT[1-6]* {set kind lut}
            default {continue}
        }
        set path [get_property PARENT $c]
        while {![dict exists $scope $path] && $path ne ""} {
            set cut [string last "/" $path]
            set path [string range $path 0 [expr {$cut-1}]]
        }
        if {[dict exists $scope $path]} {
            dict incr counts [list [dict get $scope $path] $path $kind]
        }
    }
    set f [open resource-owners.tsv w]
    dict for {key number} $counts {puts $f "[join $key \t]\t$number"}
    close $f
}
