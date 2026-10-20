use bevy_ecs::prelude::*;
use std::env;
use std::hint::black_box;
use std::process;
use std::time::Instant;

const SYSTEM: &str = "bevy";
const VERSION: &str = "0.20.0";

#[derive(Component, Clone, Copy)]
struct Position {
    x: f64,
    y: f64,
}

#[derive(Component, Clone, Copy)]
struct Velocity {
    x: f64,
    y: f64,
}

struct Args {
    workload: String,
    entities: usize,
    iterations: usize,
    samples: usize,
    warmup: usize,
}

fn parse_usize(flag: &str, value: Option<String>) -> usize {
    value
        .unwrap_or_else(|| fail(&format!("missing value for {flag}")))
        .parse()
        .unwrap_or_else(|_| fail(&format!("invalid integer for {flag}")))
}

fn fail(message: &str) -> ! {
    eprintln!("error: {message}");
    process::exit(2);
}

fn parse_args() -> Args {
    let mut result = Args {
        workload: String::new(),
        entities: 0,
        iterations: 0,
        samples: 0,
        warmup: 0,
    };
    let mut args = env::args().skip(1);
    while let Some(flag) = args.next() {
        match flag.as_str() {
            "--workload" => {
                result.workload = args.next().unwrap_or_else(|| fail("missing workload"))
            }
            "--entities" => result.entities = parse_usize(&flag, args.next()),
            "--iterations" => result.iterations = parse_usize(&flag, args.next()),
            "--samples" => result.samples = parse_usize(&flag, args.next()),
            "--warmup" => result.warmup = parse_usize(&flag, args.next()),
            _ => fail(&format!("unknown argument: {flag}")),
        }
    }
    if result.entities == 0 || result.iterations == 0 || result.samples == 0 {
        fail("entities, iterations and samples must be greater than zero");
    }
    result
}

fn entity_cycle_once(world: &mut World, count: usize) {
    let mut ids = Vec::with_capacity(count);
    for _ in 0..count {
        ids.push(world.spawn(Position { x: 1.0, y: 2.0 }).id());
    }
    for entity in ids {
        let _ = world.despawn(entity);
    }
}

fn add_remove_once(world: &mut World, ids: &[Entity]) {
    for &entity in ids {
        world
            .entity_mut(entity)
            .insert(Velocity { x: 0.5, y: -0.25 });
    }
    for &entity in ids {
        world.entity_mut(entity).remove::<Velocity>();
    }
}

fn iterate_once(world: &mut World, query: &mut QueryState<(&mut Position, &Velocity)>) {
    for (mut position, velocity) in query.iter_mut(world) {
        position.x += velocity.x;
        position.y += velocity.y;
    }
}

fn checksum_positions(world: &mut World) -> f64 {
    let mut query = world.query::<&Position>();
    query
        .iter(world)
        .map(|position| position.x + position.y)
        .sum()
}

fn run_sample(args: &Args) -> (u128, f64) {
    match args.workload.as_str() {
        "entity_cycle" => {
            let mut world = World::new();
            for _ in 0..args.warmup {
                entity_cycle_once(&mut world, args.entities);
            }
            let start = Instant::now();
            for _ in 0..args.iterations {
                entity_cycle_once(&mut world, args.entities);
            }
            let elapsed = start.elapsed().as_nanos();
            black_box((&world, elapsed));
            let checksum = checksum_positions(&mut world);
            (elapsed, checksum)
        }
        "add_remove" => {
            let mut world = World::new();
            let ids: Vec<Entity> = (0..args.entities)
                .map(|_| world.spawn(Position { x: 1.0, y: 2.0 }).id())
                .collect();
            // Register the destination archetype before the warmup/timed region.
            add_remove_once(&mut world, &ids);
            for _ in 0..args.warmup {
                add_remove_once(&mut world, &ids);
            }
            let start = Instant::now();
            for _ in 0..args.iterations {
                add_remove_once(&mut world, &ids);
            }
            let elapsed = start.elapsed().as_nanos();
            let checksum = checksum_positions(&mut world);
            black_box(checksum);
            (elapsed, checksum)
        }
        "iterate" => {
            let mut world = World::new();
            world.spawn_batch(
                (0..args.entities)
                    .map(|_| (Position { x: 1.0, y: 2.0 }, Velocity { x: 0.5, y: -0.25 })),
            );
            let mut query = world.query::<(&mut Position, &Velocity)>();
            for _ in 0..args.warmup {
                iterate_once(&mut world, &mut query);
            }
            let start = Instant::now();
            for _ in 0..args.iterations {
                iterate_once(&mut world, &mut query);
            }
            let elapsed = start.elapsed().as_nanos();
            let checksum = checksum_positions(&mut world);
            black_box(checksum);
            (elapsed, checksum)
        }
        _ => fail(&format!("unsupported workload: {}", args.workload)),
    }
}

fn main() {
    let args = parse_args();
    for sample in 0..args.samples {
        let (duration_ns, checksum) = run_sample(&args);
        println!(
            "{{\"protocol\":\"ecs-bench/v1\",\"system\":\"{SYSTEM}\",\"system_version\":\"{VERSION}\",\"language\":\"Rust\",\"workload\":\"{}\",\"entities\":{},\"iterations\":{},\"sample\":{},\"duration_ns\":{},\"ns_per_iteration\":{:.6},\"checksum\":{:.6}}}",
            args.workload,
            args.entities,
            args.iterations,
            sample,
            duration_ns,
            duration_ns as f64 / args.iterations as f64,
            checksum
        );
    }
}
