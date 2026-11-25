source extract.tcl

proc main {} {
    set config [open request.tsv r]
    set values {}
    foreach line [split [string trimright [read $config] "\n"] "\n"] {
        lappend values [encoding convertfrom utf-8 [binary decode hex $line]]
    }
    close $config
    lassign $values kind input name requested_run build max_paths nworst part top xdc
    set_param general.maxThreads 2
    if {$kind eq "doctor"} {
        set commands {get_timing_paths report_timing report_timing_summary report_design_analysis report_clock_interaction check_timing get_cells get_pins get_nets get_clocks get_property report_property get_runs open_run open_checkpoint open_project save_project_as launch_runs}
        foreach cmd $commands {
            puts "TIMINGLENS_COMMAND $cmd [expr {[llength [info commands $cmd]] != 0}]"
        }
        puts "TIMINGLENS_PART [expr {[llength [get_parts -quiet $part]] == 1}]"
        return
    }
    set run ""
    set stale 0
    if {$kind eq "checkpoint"} {
        puts "TimingLens: opening checkpoint"
        open_checkpoint $input
        set top [current_design]
    } elseif {$kind eq "demo"} {
        puts "TimingLens: synthesizing $name"
        read_verilog -sv $input
        read_xdc $xdc
        synth_design -top $top -part $part
        if {$build eq "route"} {
            puts "TimingLens: placing and routing $name"
            opt_design
            place_design
            route_design
        }
        write_checkpoint design.dcp
    } else {
        puts "TimingLens: opening project read-only"
        open_project -read_only $input
        if {$build ne "none"} {
            puts "TimingLens: creating isolated build project"
            save_project_as -exclude_run_results -scan_for_includes timinglens-build [file normalize build]
            config_ip_cache -disable_cache
        }
        set synth [current_run -synthesis]
        set impl [current_run -implementation]
        set run $requested_run
        if {$run eq ""} {
            if {$build eq "synth"} {
                set run $synth
            } elseif {$build eq "route"} {
                set run $impl
            } else {
                foreach candidate [list $impl $synth] {
                    if {$candidate ne "" && [tl::prop PROGRESS $candidate] eq "100%" &&
                        [string match "*Complete*" [tl::prop STATUS $candidate]]} {
                        set run $candidate
                        break
                    }
                }
            }
        }
        if {$run eq ""} { error "No completed synthesis or implementation run. Select a run or request an isolated build." }
        set obj [get_runs -quiet [list $run]]
        if {[llength $obj] != 1 || [tl::prop NAME $obj] ne $run} { error "Run does not exist: $run" }
        if {$build ne "none"} {
            if {($build eq "route") ne ([tl::prop IS_IMPLEMENTATION $obj] eq "1")} {
                error "Selected run does not match the requested build stage"
            }
            # Run hooks in a copied project may still point outside that project.
            foreach candidate [get_runs] {
                foreach property [list_property $candidate] {
                    if {[string match "STEPS.*.TCL.*" $property] && [tl::prop $property $candidate] ne ""} {
                        error "Isolated builds require empty run hooks ($candidate $property). Use an existing run."
                    }
                }
            }
            puts "TimingLens: building $run in the isolated project"
            if {$build eq "route"} {
                if {$synth ne "" && [tl::prop PROGRESS $synth] ne "100%"} {
                    launch_runs $synth -jobs 1
                    wait_on_run $synth
                    if {[tl::prop PROGRESS $synth] ne "100%"} { error "Synthesis failed. See the isolated build logs." }
                }
                launch_runs $run -to_step route_design -jobs 1
            } else {
                launch_runs $run -jobs 1
            }
            wait_on_run $run
        }
        if {[tl::prop PROGRESS $obj] ne "100%" || ![string match "*Complete*" [tl::prop STATUS $obj]]} {
            error "Run did not complete: $run ([tl::prop STATUS $obj])"
        }
        set state [tl::prop NEEDS_REFRESH $obj]
        set stale [expr {$state eq "1" || [string equal -nocase $state true]}]
        set source_set [get_filesets -quiet [tl::prop SRCSET $obj]]
        set top [tl::prop TOP $source_set]
        if {$top eq ""} { set top [tl::prop TOP [current_fileset]] }
        puts "TimingLens: opening run $run"
        open_run $run
    }
    tl::collect $kind $input $name $top $run $max_paths $nworst $stale
    puts "TimingLens: extraction complete"
}

if {[catch {main} reason options]} {
    puts stderr "TimingLens: $reason"
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
