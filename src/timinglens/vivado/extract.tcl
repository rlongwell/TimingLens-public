# Read-only collection in the design currently in memory. Hex fields preserve Tcl names.
namespace eval tl {
    variable out
    variable seen
    variable props
    array set seen {}
    array set props {}
}

proc tl::emit {kind args} {
    variable out
    set fields [list $kind]
    foreach value $args { lappend fields [binary encode hex [encoding convertto utf-8 $value]] }
    puts $out [join $fields "\t"]
}
proc tl::prop {key object} {
    if {$object eq ""} { return "" }
    if {[catch {get_property -quiet $key $object} value]} { return "" }
    return $value
}
proc tl::values {object keys} {
    set result {}
    foreach key $keys { lappend result [tl::prop $key $object] }
    return $result
}
proc tl::source_file {filename type} {
    variable seen
    if {$filename eq "" || ![file isfile $filename]} { return }
    set filename [file normalize $filename]
    if {[info exists seen(source,$filename)]} { return }
    set seen(source,$filename) 1
    tl::emit SOURCE $filename $type
}
proc tl::cell {c} {
    variable seen
    set name [tl::prop NAME $c]
    if {$name eq ""} { return "" }
    if {[info exists seen(cell,$name)]} { return $name }
    set seen(cell,$name) 1
    set parent [tl::prop PARENT $c]
    if {$parent ne "" && $parent ne $name} { tl::cell $parent }
    set filename [tl::prop FILE_NAME $c]
    if {$filename ne "" && [file isfile $filename]} {
        set filename [file normalize $filename]
        tl::source_file $filename ""
    }
    tl::emit CELL $name $parent {*}[tl::values $c {
        REF_NAME ORIG_REF_NAME ORIG_CELL_NAME LOC BEL INIT IS_SEQUENTIAL IS_PRIMITIVE
    }] $filename {*}[tl::values $c {LINE_NUMBER PRIMITIVE_TYPE DONT_TOUCH CLOCK_REGION}]
    foreach property {HD.RECONFIGURABLE IS_LOC_FIXED IS_BEL_FIXED} {
        set value [tl::prop $property $c]
        if {$value ne ""} { tl::emit CELLPROP $name $property $value }
    }
    return $name
}
proc tl::pin {p {port 0}} {
    variable seen
    set name [tl::prop NAME $p]
    if {$name eq ""} { return "" }
    if {[info exists seen(pin,$name)]} { return $name }
    set seen(pin,$name) 1
    set c ""
    if {!$port} { set c [tl::cell [lindex [get_cells -quiet -of_objects $p] 0]] }
    tl::emit PIN $name $c $port {*}[tl::values $p {DIRECTION REF_PIN_NAME}]
    return $name
}
proc tl::net {n} {
    variable seen
    set name [tl::prop NAME $n]
    if {$name eq ""} { return "" }
    if {[info exists seen(alias,$name)]} { return $seen(alias,$name) }
    set anchor [lindex [get_pins -quiet -of_objects $n] 0]
    if {$anchor eq ""} { set anchor [lindex [get_ports -quiet -of_objects $n] 0] }
    set canonical {}
    set segments {}
    if {$anchor ne ""} {
        set canonical [get_nets -quiet -segments -top_net_of_hierarchical_group -of_objects $anchor]
        set segments [get_nets -quiet -segments -of_objects $anchor]
    }
    if {[llength $canonical] == 1} { set n [lindex $canonical 0] }
    set key [tl::prop NAME $n]
    set seen(alias,$name) $key
    if {[info exists seen(net,$key)]} { return $key }
    set seen(net,$key) 1
    if {[llength $segments] == 0} { set segments [list $n] }
    set drivers [get_pins -quiet -leaf -of_objects $segments -filter {DIRECTION == OUT || DIRECTION == INOUT}]
    set sinks [get_pins -quiet -leaf -of_objects $segments -filter {DIRECTION == IN || DIRECTION == INOUT}]
    set driver_names {}
    set sink_names {}
    set sink_count [llength $sinks]
    foreach p $drivers { lappend driver_names [tl::pin $p] }
    foreach p [lrange $sinks 0 127] { lappend sink_names [tl::pin $p] }
    foreach p [get_ports -quiet -of_objects $segments] {
        set p_name [tl::pin $p 1]
        switch [tl::prop DIRECTION $p] {
            IN { lappend driver_names $p_name }
            OUT { incr sink_count; lappend sink_names $p_name }
            INOUT { lappend driver_names $p_name; incr sink_count; lappend sink_names $p_name }
        }
    }
    set aliases [get_property NAME $segments]
    tl::emit NET $key $sink_count [expr {$sink_count <= 128}] {*}[tl::values $n {ROUTE_STATUS TYPE IS_CLOCK}]
    foreach alias $aliases {
        set seen(alias,$alias) $key
        tl::emit ALIAS $key $alias
    }
    foreach p [lsort -unique $driver_names] { tl::emit DRIVER $key $p }
    foreach p [lsort -unique $sink_names] { tl::emit SINK $key $p }
    return $key
}
proc tl::optional_report {filename command} {
    if {[catch {uplevel 1 $command} message]} {
        tl::emit WARNING "$filename unavailable: $message"
    }
}
proc tl::collect {kind input name top run max_paths nworst stale {scope design}} {
    variable out
    variable seen
    variable props
    array unset seen
    array unset props
    set out [open records.tsv w]
    fconfigure $out -encoding ascii -translation lf -buffering line
    tl::emit META $name [version -short] [tl::prop PART [current_design]] $top $input $run $kind
    if {$stale} {
        tl::emit STALE 1
        tl::emit WARNING "Vivado marked the run as out of date. Direct source attribution was suppressed."
    }
    foreach f [get_files -quiet] {
        tl::source_file [tl::prop NAME $f] [tl::prop FILE_TYPE $f]
    }
    foreach c [get_clocks -quiet] {
        set clock_name [tl::prop NAME $c]
        tl::emit CLOCK $clock_name {*}[tl::values $c {PERIOD IS_GENERATED MASTER_CLOCK}]
        foreach edge [tl::prop WAVEFORM $c] { tl::emit WAVE $clock_name $edge }
        foreach source [tl::prop SOURCE_PINS $c] { tl::emit CLOCKSOURCE $clock_name $source }
    }
    puts "TimingLens: collecting timing summary and constraint checks"
    tl::optional_report timing_summary.rpt {report_timing_summary -delay_type min_max -max_paths 1 -file timing_summary.rpt}
    tl::optional_report check_timing.rpt {check_timing -verbose -file check_timing.rpt}
    tl::optional_report clock_interaction.rpt {report_clock_interaction -file clock_interaction.rpt}
    tl::optional_report route_status.rpt {report_route_status -file route_status.rpt}
    set index 0
    foreach {analysis delay_type} {setup max hold min} {
        puts "TimingLens: collecting $analysis paths"
        set scope_args {}
        if {$scope eq "register_paths"} {
            set scope_args [list -from [all_registers] -to [all_registers]]
        } elseif {$scope ne "design"} { error "Unsupported collection scope: $scope" }
        set paths [get_timing_paths -delay_type $delay_type -max_paths $max_paths -nworst $nworst \
            -unique_pins -no_report_unconstrained -routable_nets -sort_by slack {*}$scope_args]
        if {[llength $paths] > 0} {
            tl::optional_report "$analysis-design-analysis.rpt" [list report_design_analysis -of_timing_paths \
                [lrange $paths 0 19] -file "$analysis-design-analysis.rpt"]
        }
        set detail [open "$analysis-paths.rpt" w]
        fconfigure $detail -encoding utf-8 -translation lf
        foreach p $paths {
            incr index
            set id [format P%05d $index]
            if {$index == 1} {
                report_property -all $p -file timing_path_properties.rpt
            }
            tl::emit PATH $id $analysis {*}[tl::values $p {
                STARTPOINT_PIN ENDPOINT_PIN STARTPOINT_CLOCK ENDPOINT_CLOCK GROUP CORNER
                SLACK REQUIREMENT ARRIVAL_TIME REQUIRED_TIME DATAPATH_DELAY DATAPATH_LOGIC_DELAY
                DATAPATH_NET_DELAY SKEW UNCERTAINTY LOGIC_LEVELS DELAY_TYPE
                EXCEPTION CLOCK_PESSIMISM STARTPOINT_CLOCK_DELAY ENDPOINT_CLOCK_DELAY ROUTABLE_NETS
            }]
            foreach prop {STARTPOINT_PIN ENDPOINT_PIN} {
                set boundary [tl::prop $prop $p]
                set endpoint_object [get_pins -quiet [list $boundary]]
                if {[llength $endpoint_object] != 1 || [tl::prop NAME $endpoint_object] ne $boundary} {
                    set endpoint_object [get_ports -quiet [list $boundary]]
                    if {[llength $endpoint_object] == 1 && [tl::prop NAME $endpoint_object] eq $boundary} {
                        tl::pin $endpoint_object 1
                    }
                } else {
                    tl::pin $endpoint_object
                }
            }
            foreach c [get_cells -quiet -of_objects $p] { tl::emit PCELL $id [tl::cell $c] }
            foreach pin [get_pins -quiet -of_objects $p] { tl::emit PPIN $id [tl::pin $pin] }
            foreach n [get_nets -quiet -of_objects $p] { tl::emit PNET $id [tl::net $n] }
            if {[catch {report_timing -of_objects $p -no_reused_label \
                -no_header -return_string} result]} {
                tl::emit WARNING "$id detail unavailable: $result"
            } else {
                puts $detail "TIMINGLENS_PATH $id"
                puts $detail $result
            }
        }
        close $detail
    }
    close $out
}
