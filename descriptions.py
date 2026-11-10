"""Plain-language explanations based on location and file type, not file contents."""
from pathlib import Path


def explain(path: Path, is_dir: bool, home: Path, base: dict) -> dict:
    parts = tuple(x.lower() for x in path.parts)
    lower = str(path).lower()
    suffix = path.suffix.lower()
    kind, risk = base['kind'], base['risk']
    content = '这个位置存放的具体内容还不能仅凭名称确定，可能是你的文件，也可能是应用保存的数据。'
    advice = '暂不建议整项删除。先展开查看，确认不再需要或已有另一份备份。'
    impact = '如果是唯一副本，删除后会丢失内容；如果被软件引用，相关功能或工程可能无法使用。'
    basis = '用途尚不明确，请核对内容'

    def use(k, r, c, a, i):
        nonlocal kind, risk, content, advice, impact, basis
        kind, risk, content, advice, impact = k, r, c, a, i
        basis = '根据所在位置和文件类型判断，未检查是否仍被工程引用'

    if kind in {'应用缓存', '剪辑应用缓存', '应用缓存候选'}:
        use(kind, risk,
            '应用为了更快打开内容而保存的临时副本，通常包括下载的图片、网页或处理结果。',
            '先退出对应应用，再清理。建议先移入废纸篓，使用正常后再清空。',
            '通常会重新生成或下载；首次打开可能变慢，也可能暂时无法离线查看部分内容。')
    elif kind == '运行日志':
        use(kind, risk, '软件记录运行过程和出错原因的文本，主要用于排查故障。',
            '不在排查问题时，旧日志通常可以清理；近期日志可先保留。',
            '一般不影响日常使用，但会丢失这段时间的故障记录，后续日志还会生成。')
    elif kind in {'开发依赖', 'Xcode 编译缓存'}:
        use(kind, risk, '编程项目下载的依赖包，或编译时生成的中间文件。',
            '确认项目有依赖清单、可以重新下载或编译后再清理。',
            '对应项目可能暂时不能运行；再次使用需要重新安装依赖或编译，会花时间和流量。')
    elif kind in {'下载文件', '安装包 / 压缩包', '虚拟机系统安装镜像'}:
        use(kind, risk, '下载到本机的文件；安装包和压缩包通常用于安装软件、解压素材或备份。',
            '确认已完成安装/解压，并且不再需要离线重装或原始文件后，可清理。',
            '删除安装包通常不会卸载已安装的软件；但会失去这份下载原件，需要时要重新下载。')
        if kind == '下载文件':
            content = '下载目录里的文件或文件夹，可能是安装包、素材、文档，也可能是唯一的一份资料。'
            impact = '删除后这份本地文件会消失；下载过不代表已有备份，若是素材还可能影响工程。'
    elif kind == 'AI 模型 / 模型缓存':
        use(kind, 'review', '本地 AI 的模型权重，相当于离线 AI 运行需要加载的“大脑”，不是普通垃圾缓存。',
            '只清理明确不用的模型，并确认还能重新下载。正在使用的模型先保留。',
            '对应的聊天、生成图片或语音功能可能无法运行；重新下载往往需要数 GB 流量。')
    elif kind in {'工具运行环境', 'AI 工具工作数据'}:
        use(kind, 'caution', 'AI/开发工具使用的程序组件、运行环境、会话或设置。',
            '不建议为了腾空间整目录删除；先在工具内管理会话、模型或插件。',
            '可能导致工具无法启动、插件不可用，或丢失会话与设置。')
    elif kind == '视频 / 音频素材':
        use(kind, 'caution', '视频或音频文件，可能是原始素材、配音，也可能是导出的成片。',
            '先确认工程是否还在引用它。已归档到其他磁盘、且不再需要本机副本时再清理。',
            '唯一副本会丢失；被剪辑工程引用时会出现素材丢失、黑画面或无声。')
    elif kind in {'应用数据', '应用共享数据'}:
        use(kind, 'caution', '软件保存的工作数据，可能混有登录信息、数据库、下载内容和个人设置。',
            '先展开查看具体子目录，或使用该软件自带的存储空间管理。',
            '整目录删除可能让软件恢复初始状态、要求重新登录，或丢失本地资料。')
    elif kind == 'iPhone / iPad 备份':
        use(kind, 'caution', '通过电脑保存的手机/平板备份，可能用于恢复旧设备的数据。',
            '先确认有较新的完整备份，再在 Finder 的设备备份管理中删除旧备份。',
            '将无法再使用这一份备份恢复设备；不等于删除手机当前正在使用的数据。')
    elif kind == 'macOS 服务缓存':
        use(kind, 'caution', 'macOS 后台服务维护的数据，例如索引、分析结果或系统资源。',
            '建议让系统自行管理，不手动整目录删除。',
            '可能触发重新索引或分析，短时间增加 CPU、耗电和磁盘占用。')

    jianying = any(x in {'jianyingpro', 'capcut', 'com.lemon.lvpro'} or x.startswith('com.lveditor') for x in parts)
    if jianying:
        use('剪映工作数据', 'caution',
            '剪映的工作目录，可能同时包含草稿、视频素材、历史备份、已下载资源和缓存；不等于“可清理缓存”。',
            '先展开，分别看草稿、备份和缓存。不要把整个剪映目录当垃圾删除。',
            '整目录删除可能造成草稿消失、素材丢失、设置重置，或需要重新下载资源。')
        # Specific contextual rules must win over generic suffixes such as .mp4/.bak.
        if '.backup' in parts or (suffix == '.bak' and 'projects' in parts):
            use('剪映 · 工程历史备份', 'caution',
                '保存/打开/关闭工程时留下的旧版本和恢复文件；它们不是导出的成片，也不一定计入软件的缓存清理。',
                '当前工程能正常打开、已有完整备份后，可考虑清理不再需要的旧历史版本。先移入废纸篓更稳妥。',
                '会失去这些旧版本的回退和故障恢复能力。不能保证删掉后所有恢复功能都不受影响。')
        elif any(x.startswith('.cloud_cache') for x in parts):
            use('剪映 · 云草稿本地副本', 'caution',
                '从云空间下载或为同步保留在本机的草稿、素材等文件。',
                '先在剪映确认云端草稿已同步完成、可以正常打开，再使用软件内的管理功能处理。',
                '可能需要重新下载，离线时无法使用；未同步的内容可能是唯一副本。')
        elif '.recycle_bin' in parts:
            use('剪映 · 草稿回收区', 'review',
                '剪映内部暂存已删除草稿的位置，通常用来恢复误删的项目。',
                '确认这些草稿不再需要后，优先在剪映的回收站里清理。',
                '将失去恢复这些草稿的机会；它与 macOS 废纸篓是不同的位置。')
        elif 'supplysstore' in parts:
            use('剪映 · 算法模型与组件', 'caution',
                '剪映某些智能功能需要的模型或配套资源，例如此类目录可含 ONNX 模型。',
                '不建议按普通缓存手动删除；优先让剪映自行管理。',
                '智能处理功能可能不可用，或需要重新下载模型，离线时可能无法恢复。')
        elif 'cache' in parts or 'caches' in parts:
            use('剪映 · 缓存与下载资源', 'review',
                '剪映生成的中间结果和下载资源，可能包含音乐、识别音频、特效、缩略图等，不全是同一种缓存。',
                '优先清理剪映设置里列出的可清理部分；手动处理前退出剪映并展开核对。',
                '有的会重新计算，有的需要重新下载；项目预览、离线资源或处理速度可能受影响。')
            cache_rules = {
                'recognize': ('语音识别中间音频', '通常是识别语音/字幕时生成的中间音频，可包含体积很大的 PCM 文件。',
                              '确认没有正在进行的识别任务，退出剪映后再处理，优先使用软件内清理。',
                              '再次识别可能需要重新处理；不要把工程唯一的原始录音当成中间文件。'),
                'music': ('已下载音乐', '剪映下载到本机的背景音乐，常见为 MP3 等音频文件。',
                          '确认当前工程不依赖这些离线音乐后再清理，优先从剪映内操作。',
                          '可能需要重新下载；断网或音乐下架时，相关项目可能无法正常使用这些音乐。'),
                'framethumbnail': ('视频缩略图', '为了快速浏览时间线生成的小预览图片。',
                                   '退出剪映后通常可以重建；优先通过软件清理。',
                                   '下次打开工程可能重新生成缩略图，短时间预览变慢。'),
                'audiowave': ('音频波形预览', '时间线上显示声音高低起伏所用的波形数据，不是音频原文件本身。',
                              '退出剪映后通常可重建；清理前确认路径确实在 audioWave 缓存内。',
                              '再次打开工程时可能重新分析声音并绘制波形。'),
                'segmentprerendercache': ('预渲染视频', '为了让时间线更流畅而提前渲染的片段，不是最终导出的成片。',
                                         '确认当前没有渲染/导出任务后，优先从剪映内清理。',
                                         '之后需要重新渲染；预览可能暂时变卡，但不是给电脑增加性能。'),
                'agencycache': ('代理视频缓存', '可能是供剪辑预览使用的代理视频，也就是原视频的低负载替代版本。',
                                '确认原始素材完整且可重新生成代理后再处理。',
                                '可能退回原画质素材播放，时间线变卡，或需要重新生成代理。'),
                'effect': ('已下载特效资源', '特效使用的图片、模型和其他下载文件。',
                           '确认不用这些资源，或可以重新下载后再清理。',
                           '使用相关特效的工程可能需要下载资源，离线时可能显示不完整。'),
                'image': ('图片缓存', '剪映下载或生成的图片相关缓存；仅凭目录无法确定每张图的用途。',
                          '优先在剪映内清理，别把它与工程 Resources 素材目录混淆。',
                          '可能重新生成或下载图片；若工程仍引用某些文件，需重新定位素材。'),
                'aitexttemplate': ('AI 文字模板资源', '文字模板、字体或模板效果需要的本地资源。',
                                   '确认不再使用对应模板，或能够重新下载后再清理。',
                                   '相关模板可能重新下载，字体和文字效果也可能需要恢复。'),
                'ilasdkdb': ('智能功能数据库', '智能分析组件维护的数据；仅凭文件名无法确认哪些记录可以安全移除。',
                             '不建议手动删数据库，优先使用剪映提供的清理入口。',
                             '可能重新分析素材，或影响相关智能功能的已有分析结果。'),
            }
            for segment, (title, c, a, i) in cache_rules.items():
                if segment in parts:
                    use('剪映 · '+title, 'caution' if segment == 'ilasdkdb' else 'review', c, a, i)
                    break
        elif 'log' in parts or 'logs' in parts:
            use('剪映 · 运行日志', 'review', '剪映记录运行和报错的文件，不是草稿和素材。',
                '不在排查故障时，关闭剪映后可考虑清理旧日志。',
                '通常不影响剪辑，但会失去旧的故障排查记录；软件还会生成新日志。')
        elif 'cef' in parts:
            use('剪映 · 内嵌网页数据', 'caution', '剪映内的网页界面保存的数据，可能混有缓存、登录状态和本地设置。',
                '不建议把整个 CEF 目录当缓存删除，先检查其缓存子目录。',
                '可能需要重新登录、重新加载页面，或重置部分界面状态。')
        elif 'config' in parts or 'mmkv' in parts:
            use('剪映 · 设置与状态', 'caution', '剪映保存偏好设置或工作状态的小型数据文件。',
                '通常占用不大，不建议为腾空间删除。',
                '可能重置偏好、路径设置或登录/工作状态。')
        elif 'projects' in parts or 'com.lveditor.draft' in parts or 'jianyingpro drafts' in parts:
            use('剪映 · 草稿工程', 'caution', '还可以继续编辑的剪辑工程，内部可能带有素材、副本、时间线和历史备份。',
                '已完成的工程先归档并确认备份能打开，再在剪映内删除不再需要的草稿。',
                '可能丢失继续编辑的能力；仅有导出的 MP4 不能还原原来的时间线。')
            if any(x in parts for x in ('resources', 'video', 'aigc_material')) or suffix in {'.mp4', '.mov', '.wav', '.mp3', '.m4a', '.png', '.jpg'}:
                use('剪映 · 工程使用的素材', 'caution', '工程携带或生成的视频、图片、配音等资源；同名也不代表可以随便删。',
                    '确认工程不再引用它，或完成可用的工程归档后再处理。',
                    '可能出现素材丢失、画面变黑、无声或 AI 生成内容丢失。')
            elif 'timelines' in parts or 'subdraft' in parts or path.name.lower().startswith(('draft_info', 'draft_content', 'draft_meta')):
                use('剪映 · 时间线与编辑信息', 'caution', '记录剪辑顺序、轨道、字幕、效果或子草稿，是工程的重要组成部分。',
                    '不要单独删除。需要清理旧工程时，在剪映里按整个草稿管理。',
                    '可能导致工程打不开、编辑内容缺失；导出视频不能替代这些编辑信息。')

    if not jianying and any(x in lower for x in ('davinci', 'blackmagic')):
        use('达芬奇 · 工程与工作数据', 'caution', '达芬奇可能保存的工程、素材、设置或工作数据，不等同于渲染缓存。',
            '先在达芬奇中备份工程/工程库，再按缓存和素材分别处理。',
            '误删可能使工程无法打开、素材离线或设置丢失。')
        if 'cacheclip' in parts:
            use('达芬奇 · 渲染缓存', 'review', '用于加快时间线回放的预渲染片段。',
                '优先使用达芬奇“删除渲染缓存”，确认没有渲染任务后操作。',
                '再次播放可能需要重新渲染；缓存恢复前时间线可能变慢。')
        elif 'proxymedia' in parts or 'optimizedmedia' in parts:
            use('达芬奇 · 代理 / 优化媒体', 'review', '为流畅剪辑生成的替代媒体，不一定是原始素材。',
                '确认原始素材完整可用、能够重新生成后，再在软件中清理。',
                '可能退回原始素材播放，增加电脑负担，或需要重新生成代理。')
        elif 'resolve disk database' in parts or 'resolve projects' in parts:
            use('达芬奇 · 工程库', 'caution', '保存可继续编辑的达芬奇工程及相关数据库。',
                '不要手动删除数据库。先导出工程或备份整个工程库，再在项目管理器中处理。',
                '可能丢失工程与时间线，导出的成片无法还原编辑过程。')
    if not jianying and any(x in lower for x in ('wechat', 'weixin', 'com.tencent.xin')):
        use('微信 · 聊天与附件', 'caution', '微信保存的聊天记录、图片、视频、语音和收到的文件，可能混在一个目录中。',
            '优先打开微信的“存储空间”管理，按聊天对象和附件类型清理。',
            '旧聊天中的图片、视频或文件可能再也打不开，整目录删除还可能影响聊天记录。')
        if suffix in {'.db', '.sqlite', '.sqlite3'}:
            use('微信 · 聊天数据库', 'caution', '可能用于保存聊天记录或索引，不是普通可清理缓存。',
                '不建议手动删除；先通过微信备份与存储管理处理。',
                '可能丢失聊天记录，或导致客户端需要重新登录/修复数据。')
    if not jianying and ('steamapps' in parts or '/application support/steam' in lower):
        use('Steam · 游戏与本地数据', 'caution', 'Steam 下载的游戏、创意工坊资源、客户端设置等；不是单纯的下载缓存。',
            '优先在 Steam → 设置 → 存储空间里卸载不玩的游戏。',
            '游戏或模组可能无法启动，需要重新下载；部分游戏还有本地存档要先备份。')
        if 'downloading' in parts:
            use('Steam · 未完成下载', 'review', '正在下载或更新的游戏分块和临时文件。',
                '先在 Steam 取消不需要的下载任务，再清理其剩余文件。',
                '可能丢失已下载的进度，需要从头下载或重新校验。')
        elif 'shadercache' in parts:
            use('Steam · 游戏着色器缓存', 'review', '游戏为更快渲染画面生成或下载的着色器数据。',
                '退出游戏和 Steam 后可考虑清理；保留它有助于减少重新编译。',
                '下次游戏启动可能重新编译，首次运行可能变慢或出现短暂卡顿。')
    if any(x.endswith('.photoslibrary') for x in parts):
        use('照片 · 照片资料库', 'caution', '照片应用管理的原图、视频、编辑记录及资料库信息。',
            '先确认完整备份和云端同步状态，使用照片应用管理，不手动拆删内部文件。',
            '可能丢失照片或破坏资料库；云端同步也可能传播删除操作。')
    elif any(x.endswith(('.pvm', '.vmdk', '.qcow2')) for x in parts):
        use('虚拟机 · 系统与文件', 'caution', '虚拟电脑的系统、软件和存放在里面的文件，不是单个安装包。',
            '确认虚拟机内资料已备份、不再使用后，在虚拟机软件中移除。',
            '可能相当于删除整台虚拟电脑，里面的 Windows、软件和文件都可能丢失。')
    elif any(x.endswith('.app') for x in parts):
        use('应用程序', 'caution', '软件本体及运行组件。',
            '不再需要的软件优先使用其卸载器或 Finder 正常卸载，不拆删内部文件。',
            '软件可能无法启动；手动删除软件本体不一定会清掉它的个人数据。')

    if kind == '个人文件' and not is_dir:
        if suffix in {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.numbers', '.pages', '.ppt', '.pptx', '.txt', '.md'}:
            use('文档 / 表格', 'caution', '你保存的文档、笔记、表格或演示文件。',
                '确认内容不再需要，或已有可用备份后再清理。',
                '这份资料会消失；如果没有备份，不能靠重新安装软件找回来。')
        elif suffix in {'.psd', '.psb', '.ai', '.blend', '.f3d', '.drp', '.aep', '.prproj'}:
            use('创作工程 / 源文件', 'caution', '用于继续编辑设计、模型、视频或动画的源工程。',
                '先归档源文件和引用素材，再删除已确认不需要的副本。',
                '可能失去继续修改作品的能力；导出的图片或视频通常不能代替源工程。')
        elif suffix in {'.jpg', '.jpeg', '.png', '.heic', '.raw', '.dng', '.mp3', '.m4a', '.flac'}:
            use('图片 / 音频文件', 'caution', '图片、照片、录音或音乐，可能是个人资料，也可能被工程引用。',
                '确认不再需要且不是唯一副本后再清理。',
                '照片或声音文件会消失，被工程引用时还可能导致素材丢失。')
    if '/.cache/magpie' in lower and risk != 'protected':
        use('语音工具缓存 / 资源', 'review', '可能是语音工具下载或生成的资源，也可能包含本地语音模型。',
            '先展开确认是否为模型；不使用或可以重新下载时再清理。',
            '可能需要重新下载，或使对应的离线语音功能暂时无法使用。')

    if base['risk'] == 'protected':
        risk = 'protected'
        advice = '这里只展示占用，不允许通过本工具直接删除。'
        if any(x in lower for x in ('/cloudstorage', '/mobile documents')):
            content = '云盘同步或 iCloud 文件，不等同于本机临时缓存。'
            impact = '删除可能同步到其他设备。只想腾本机空间时，优先用云盘的“移除下载”。'
        elif any(x in parts for x in ('.ssh', '.gnupg', '.aws', 'keychains', 'preferences')):
            content = '账号凭据、密钥或重要设置。'
            impact = '删除可能导致无法登录、无法连接服务或设置丢失。'
        elif path == home / '.Trash':
            content = '你移入 macOS 废纸篓的文件，它们仍在占用空间。'
            impact = '清空后不能从本工具撤回。请在 Finder 检查无误后处理。'
        elif base['kind'] == '应用 / 系统 / 共享数据':
            content = '应用或系统维护的文件，可能由多个程序共同使用。'
            impact = '随意删除可能影响软件或系统功能，优先使用对应的卸载/管理入口。'
        else:
            impact = '这个目录包含多类内容，整项删除影响范围过大；可以展开查看允许处理的子项。'
    owner = '用途待核对'
    owners = [('jianying', '剪映'), ('com.lveditor', '剪映'), ('capcut', 'CapCut'),
              ('com.lemon.lvpro', '剪映'), ('wechat', '微信'), ('weixin', '微信'),
              ('com.tencent.xin', '微信'), ('steam', 'Steam'), ('com.netease.163music', '网易云音乐'),
              ('microsoft edge', 'Microsoft Edge'), ('google/chrome', 'Google Chrome'),
              ('quark', '夸克网盘'), ('123pan', '123 云盘'), ('ugreen', '绿联客户端'),
              ('autodesk', 'Autodesk / Fusion'), ('lmstudio', 'LM Studio'),
              ('ollama', 'Ollama'), ('huggingface', 'AI 模型工具'), ('codex', 'Codex'),
              ('claude', 'Claude'), ('parallels', 'Parallels'), ('magpie', '语音工具'),
              ('/.cache/uv', 'Python 开发工具'), ('/.npm', 'Node.js 开发工具')]
    for fragment, label in owners:
        if fragment in lower:
            owner = label
            break
    return dict(kind=kind, risk=risk, content=content, advice=advice, impact=impact, owner=owner,
                basis=basis, note=advice+' '+impact)
